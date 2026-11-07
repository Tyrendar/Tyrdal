from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.errors import DomainError
from apps.accounts.models import User
from apps.audit.services import record
from apps.catalog.models import Barcode
from apps.catalog.normalize import canonical, clean

from .models import Stocktake, StockCount, StocktakeStatus

MAX_QUANTITY = 10_000_000
MAX_PRICE = Decimal("99999999999999")
MAX_BATCH = 500
_ARABIC_DECIMAL = "٫"  # Persian/Arabic decimal separator


def is_countable(st: Stocktake) -> bool:
    return st.status == StocktakeStatus.OPEN and st.date <= timezone.localdate()


def check_countable(st: Stocktake) -> None:
    if st.status != StocktakeStatus.OPEN:
        raise DomainError("stocktake_closed", "This stocktake is closed", http_status=409)
    if st.date > timezone.localdate():
        raise DomainError("stocktake_not_started", f"Counting starts on {st.date}", http_status=409)


def parse_price(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        p = Decimal(str(v).replace(",", "").replace(_ARABIC_DECIMAL, ".").strip())
    except InvalidOperation:
        raise ValueError("invalid_price")
    if not p.is_finite() or p < 0 or p > MAX_PRICE or p != p.quantize(Decimal("0.01")):
        raise ValueError("invalid_price")
    return p


def _product_of(code: str):
    b = Barcode.objects.filter(code=code, is_active=True).select_related("product").order_by("is_derived", "pk").first()
    return b.product if b else None


@transaction.atomic
def upsert_counts(st: Stocktake, user, records: list[dict], *, device=None, sent_at: str | None = None) -> dict:
    """Create/update/delete this counter's records.

    Idempotent per record id (generated on the PDA); an older edit, by the PDA's own
    clock, never overwrites a newer one. PDA clock skew is corrected with `sent_at`.
    Returns accepted ids and per-record rejections.
    """
    st = Stocktake.objects.select_for_update().get(pk=st.pk)
    check_countable(st)
    if len(records) > MAX_BATCH:
        raise DomainError("batch_too_large", f"At most {MAX_BATCH} records per request")
    now = timezone.now()
    skew = timedelta(0)
    sent = parse_datetime(sent_at or "")
    if sent:
        skew = now - sent
        if abs(skew) < timedelta(seconds=5):
            skew = timedelta(0)

    accepted, rejected = [], []
    for r in records:
        rid = r.get("id")
        try:
            rid = str(uuid.UUID(str(rid)))
        except (TypeError, ValueError, AttributeError):
            rejected.append({"id": rid, "error": "invalid_id"})
            continue
        try:
            barcode = clean(r.get("barcode") or "")
            if not barcode or len(barcode) > 64:
                raise ValueError("invalid_barcode")
            qty = r.get("quantity")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0 or qty > MAX_QUANTITY:
                raise ValueError("invalid_quantity")
            price = parse_price(r.get("price"))
            counted_at = parse_datetime(str(r.get("counted_at") or ""))
            updated_at = parse_datetime(str(r.get("updated_at") or r.get("counted_at") or ""))
            if not counted_at or not updated_at:
                raise ValueError("invalid_time")
        except ValueError as e:
            rejected.append({"id": rid, "error": str(e)})
            continue
        counted_at, updated_at = min(counted_at + skew, now), min(updated_at + skew, now)

        existing = StockCount.objects.select_for_update().filter(pk=rid).first()
        if existing and (existing.stocktake_id != st.pk or existing.user_id != user.pk):
            rejected.append({"id": rid, "error": "not_yours"})
            continue
        if existing and existing.client_updated_at >= updated_at:
            accepted.append(rid)  # this version or a newer one is already stored
            continue
        code = canonical(barcode)
        fields = dict(barcode=barcode, code=code, product=_product_of(code), quantity=qty, price=price,
                      client_updated_at=updated_at, deleted=bool(r.get("deleted")), device=device)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save()
        else:
            StockCount.objects.create(id=rid, stocktake=st, user=user, counted_at=counted_at, **fields)
        accepted.append(rid)
    return {"accepted": accepted, "rejected": rejected}


# --- Totals and export ----------------------------------------------------------------
@dataclass
class BarcodeTotal:
    code: str
    barcode: str = ""
    title: str = ""
    quantity: int = 0
    records: int = 0
    counters: set = field(default_factory=set)
    price: Decimal | None = None
    prices: set = field(default_factory=set)
    forms: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {"code": self.code, "barcode": self.barcode, "title": self.title, "quantity": self.quantity,
                "records": self.records, "counters": len(self.counters), "price": self.price,
                "price_conflict": len(self.prices) > 1}


def totals(st: Stocktake) -> list[BarcodeTotal]:
    """Per barcode: summed quantity; the barcode as it was scanned most often; the price
    entered last (records without a price are ignored); price_conflict when records
    disagree on the price."""
    out: dict[str, BarcodeTotal] = {}
    rows = (st.counts.filter(deleted=False).order_by("counted_at")
            .values_list("code", "barcode", "quantity", "price", "user_id", "product__title"))
    for code, barcode, qty, price, uid, title in rows.iterator(chunk_size=5000):
        t = out.setdefault(code, BarcodeTotal(code))
        t.quantity += qty
        t.records += 1
        t.counters.add(uid)
        t.forms[barcode] += 1
        t.title = title or t.title
        if price is not None:
            t.price = price
            t.prices.add(price)
    for t in out.values():
        best = max(t.forms.values())
        t.barcode = [b for b, n in t.forms.items() if n == best][-1]
    return sorted(out.values(), key=lambda t: t.barcode)


def counter_summary(st: Stocktake) -> list[dict]:
    empty = lambda: {"records": 0, "quantity": 0, "codes": set(), "last_at": None}  # noqa: E731
    agg: dict[int, dict] = defaultdict(empty)
    for uid, code, qty, at in st.counts.filter(deleted=False).values_list("user_id", "code", "quantity", "counted_at"):
        a = agg[uid]
        a["records"] += 1
        a["quantity"] += qty
        a["codes"].add(code)
        a["last_at"] = max(a["last_at"], at) if a["last_at"] else at

    def row(u, uid, a, assigned):
        return {"user_id": uid, "name": u.display_name if u else str(uid), "username": u.username if u else "",
                "assigned": assigned, "records": a["records"], "quantity": a["quantity"], "barcodes": len(a["codes"]),
                "last_at": a["last_at"]}

    rows = [row(u, u.pk, agg.pop(u.pk, None) or empty(), True) for u in st.counters.all().order_by("full_name", "username")]
    # Records by someone later removed from the task still count.
    others = {u.pk: u for u in User.objects.filter(pk__in=list(agg))}
    rows += [row(others.get(uid), uid, a, False) for uid, a in agg.items()]
    return rows


def close(st: Stocktake, user, request=None) -> Stocktake:
    if st.status == StocktakeStatus.CLOSED:
        raise DomainError("stocktake_closed", "Already closed", http_status=409)
    st.status, st.closed_at, st.closed_by = StocktakeStatus.CLOSED, timezone.now(), user
    st.save(update_fields=["status", "closed_at", "closed_by"])
    record("stocktake.closed", st, user=user, request=request)
    return st


def reopen(st: Stocktake, user, request=None) -> Stocktake:
    if st.status != StocktakeStatus.CLOSED:
        raise DomainError("stocktake_open", "Not closed", http_status=409)
    st.status, st.closed_at, st.closed_by = StocktakeStatus.OPEN, None, None
    st.save(update_fields=["status", "closed_at", "closed_by"])
    record("stocktake.reopened", st, user=user, request=request)
    return st
