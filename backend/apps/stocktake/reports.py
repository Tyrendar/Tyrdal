"""Stocktaking reports. Separate from the order-checking reports.

Period basis: count records whose counting time falls in the period (warehouse-local dates);
stocktakes are listed when their date is in the period or they have records in it.
Deleted records are excluded from volumes but count as activity for active time.
Active time = gaps between a counter's consecutive records, ignoring gaps over
CHECKING["ACTIVE_GAP_SECONDS"] (same rule as checkers).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.accounts.models import User
from apps.checking.engine import active_gaps
from apps.reports.services import TZ, Period

from .models import MasterItem, MasterSource, StockCount, Stocktake, StocktakeStatus

EDIT_GRACE = timedelta(seconds=2)


def _records(p: Period, vendor: int | None = None, counter: int | None = None, live: bool = True):
    qs = StockCount.objects.filter(counted_at__gte=p.start, counted_at__lt=p.end)
    if live:
        qs = qs.filter(deleted=False)
    if vendor:
        qs = qs.filter(stocktake__vendor_id=vendor)
    if counter:
        qs = qs.filter(user_id=counter)
    return qs


def _ratio(a, b, digits=1):
    return round(a / b, digits) if b else None


def _value(rows) -> Decimal:
    return sum((Decimal(q) * pr for q, pr in rows if pr is not None), Decimal(0))


def _active_by_user(p: Period, vendor=None, counter=None) -> dict[int, int]:
    times: dict[int, list] = defaultdict(list)
    for uid, t in _records(p, vendor, counter, live=False).order_by("user_id", "counted_at").values_list("user_id", "counted_at").iterator(chunk_size=5000):
        times[uid].append(t)
    return {uid: active_gaps(ts) for uid, ts in times.items()}


# --- Overview --------------------------------------------------------------------------
def overview(p: Period, vendor: int | None = None, counter: int | None = None) -> dict:
    recs = _records(p, vendor, counter)
    agg = recs.aggregate(
        records=Count("id"), units=Sum("quantity"), barcodes=Count("code", distinct=True),
        counters=Count("user", distinct=True), vendors=Count("stocktake__vendor", distinct=True),
        stocktakes=Count("stocktake", distinct=True), typed=Count("id", filter=Q(title_typed=True)),
        with_price=Count("id", filter=Q(price__isnull=False)), no_title=Count("id", filter=Q(title="")),
    )
    st = Stocktake.objects.filter(date__gte=p.date_from, date__lte=p.date_to)
    if vendor:
        st = st.filter(vendor_id=vendor)
    if counter:
        st = st.filter(counters=counter)
    active = sum(_active_by_user(p, vendor, counter).values())
    days = defaultdict(lambda: {"records": 0, "units": 0, "counters": 0})
    for r in recs.annotate(d=TruncDate("counted_at", tzinfo=TZ)).values("d").annotate(
            n=Count("id"), u=Sum("quantity"), c=Count("user", distinct=True)):
        days[r["d"]] = {"records": r["n"], "units": r["u"] or 0, "counters": r["c"]}
    today = timezone.localdate()
    open_now = Stocktake.objects.filter(status=StocktakeStatus.OPEN)
    return {
        "period": p.as_dict(),
        "records": agg["records"], "units": agg["units"] or 0, "barcodes": agg["barcodes"],
        "counters": agg["counters"], "vendors": agg["vendors"], "stocktakes_counted": agg["stocktakes"],
        "typed_titles": agg["typed"], "with_price": agg["with_price"], "without_title": agg["no_title"],
        "value": _value(recs.values_list("quantity", "price")),
        "stocktakes_planned": st.count(), "stocktakes_closed": st.filter(status=StocktakeStatus.CLOSED).count(),
        "active_seconds": active, "records_per_hour": _ratio(agg["records"] * 3600, active),
        "now": {
            "open": open_now.filter(date__lte=today).count(),
            "upcoming": open_now.filter(date__gt=today).count(),
            "counting_today": StockCount.objects.filter(counted_at__date=today).values("user").distinct().count(),
            "new_titles_to_review": MasterItem.objects.filter(source=MasterSource.COUNTER, deleted=False).count(),
        },
        "by_day": [{"date": d.isoformat(), **v} for d, v in sorted(days.items())],
    }


# --- Counters --------------------------------------------------------------------------
def counters(p: Period, vendor: int | None = None, counter: int | None = None) -> dict:
    all_recs = _records(p, vendor, counter, live=False)
    agg = {r["user_id"]: r for r in all_recs.values("user_id").annotate(
        records=Count("id", filter=Q(deleted=False)), units=Sum("quantity", filter=Q(deleted=False)),
        barcodes=Count("code", filter=Q(deleted=False), distinct=True), stocktakes=Count("stocktake", filter=Q(deleted=False), distinct=True),
        n_deleted=Count("id", filter=Q(deleted=True)),
        typed=Count("id", filter=Q(deleted=False, title_typed=True)),
        first=Min("counted_at"), last=Max("counted_at"),
    )}
    edited: dict[int, int] = defaultdict(int)  # changed on the PDA after it was first saved
    for uid, at, upd in all_recs.filter(deleted=False).values_list("user_id", "counted_at", "client_updated_at").iterator(chunk_size=5000):
        if upd > at + EDIT_GRACE:
            edited[uid] += 1
    active = _active_by_user(p, vendor, counter)
    users = {u.pk: u for u in User.objects.filter(pk__in=list(agg))}
    rows = []
    for uid, a in agg.items():
        u, act = users.get(uid), active.get(uid, 0)
        rows.append({
            "user_id": uid, "name": u.display_name if u else str(uid), "username": u.username if u else "",
            "stocktakes": a["stocktakes"], "records": a["records"], "units": a["units"] or 0, "barcodes": a["barcodes"],
            "active_seconds": act, "records_per_hour": _ratio(a["records"] * 3600, act),
            "units_per_hour": _ratio((a["units"] or 0) * 3600, act, 0),
            "edited": edited.get(uid, 0), "deleted": a["n_deleted"], "typed_titles": a["typed"],
            "first_at": a["first"], "last_at": a["last"],
        })
    rows.sort(key=lambda r: (-r["records"], r["name"]))
    return {"period": p.as_dict(), "rows": rows}


# --- Vendors ---------------------------------------------------------------------------
def vendors(p: Period, vendor: int | None = None, counter: int | None = None) -> dict:
    recs = _records(p, vendor, counter)
    base = {r["stocktake__vendor_id"]: r for r in recs.values("stocktake__vendor_id", "stocktake__vendor__name").annotate(
        stocktakes=Count("stocktake", distinct=True), records=Count("id"), units=Sum("quantity"),
        barcodes=Count("code", distinct=True), counters=Count("user", distinct=True), last=Max("counted_at"),
        with_price=Count("id", filter=Q(price__isnull=False)),
    )}
    values: dict[int, list] = defaultdict(list)
    for vid, q, pr in recs.values_list("stocktake__vendor_id", "quantity", "price").iterator(chunk_size=5000):
        values[vid].append((q, pr))
    rows = [{
        "vendor_id": vid, "vendor": r["stocktake__vendor__name"], "stocktakes": r["stocktakes"], "records": r["records"],
        "units": r["units"] or 0, "barcodes": r["barcodes"], "counters": r["counters"], "last_at": r["last"],
        "with_price": r["with_price"], "value": _value(values[vid]),
    } for vid, r in base.items()]
    rows.sort(key=lambda r: (-r["units"], r["vendor"]))
    return {"period": p.as_dict(), "rows": rows}


# --- Stocktakes ------------------------------------------------------------------------
def stocktakes(p: Period, vendor: int | None = None, counter: int | None = None, status: str | None = None) -> dict:
    in_period = Q(date__gte=p.date_from, date__lte=p.date_to) | Q(counts__counted_at__gte=p.start, counts__counted_at__lt=p.end)
    qs = Stocktake.objects.filter(in_period).select_related("vendor").prefetch_related("counters").distinct()
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    if counter:
        qs = qs.filter(counters=counter)
    if status in StocktakeStatus.values:
        qs = qs.filter(status=status)
    qs = list(qs.order_by("-date", "-id")[:2000])
    live = Q(counts__deleted=False)
    stats = {r["id"]: r for r in Stocktake.objects.filter(pk__in=[s.pk for s in qs]).values("id").annotate(
        records=Count("counts", filter=live), units=Sum("counts__quantity", filter=live),
        barcodes=Count("counts__code", filter=live, distinct=True), typed=Count("counts", filter=live & Q(counts__title_typed=True)),
        first=Min("counts__counted_at", filter=live), last=Max("counts__counted_at", filter=live),
    )}
    rows = []
    for s in qs:
        a = stats.get(s.pk, {})
        first, last = a.get("first"), a.get("last")
        rows.append({
            "stocktake_id": s.pk, "vendor": s.vendor.name, "date": s.date, "status": s.status,
            "counters": ", ".join(u.display_name for u in s.counters.all()), "counters_n": s.counters.count(),
            "records": a.get("records") or 0, "units": a.get("units") or 0, "barcodes": a.get("barcodes") or 0,
            "typed_titles": a.get("typed") or 0, "first_at": first, "last_at": last,
            "elapsed_seconds": int((last - first).total_seconds()) if first and last else None, "closed_at": s.closed_at,
        })
    return {"period": p.as_dict(), "rows": rows}


# --- Titles typed by counters ------------------------------------------------------------
def new_titles(p: Period, counter: int | None = None) -> dict:
    qs = MasterItem.objects.filter(source=MasterSource.COUNTER, created_at__gte=p.start, created_at__lt=p.end).select_related("created_by")
    if counter:
        qs = qs.filter(created_by_id=counter)
    others = defaultdict(list)
    codes = list(qs.values_list("code", flat=True))
    for code, title in MasterItem.objects.filter(code__in=codes, deleted=False).exclude(source=MasterSource.COUNTER).values_list("code", "title"):
        others[code].append(title)
    rows = [{
        "id": m.pk, "barcode": m.barcode, "title": m.title, "counter": m.created_by.display_name if m.created_by else None,
        "created_at": m.created_at, "deleted": m.deleted, "other_titles": " | ".join(others.get(m.code, [])),
    } for m in qs.order_by("-created_at")[:5000]]
    return {"period": p.as_dict(), "rows": rows}
