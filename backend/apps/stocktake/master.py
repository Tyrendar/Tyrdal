"""Stocktaking master (barcode -> title list), independent of the order-checking catalog.

Import modes:
- merge (default): add new barcode+title pairs, update the price of existing ones; never removes anything.
- replace: like merge, and also removes previously *imported* items that are not in the file.
  Items added in the panel or typed by counters are never removed by an import.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.errors import DomainError
from apps.catalog.normalize import canonical, clean

from .models import MasterItem, MasterSource
from .services import parse_price

BARCODE_HEADERS = {"barcode", "بارکد", "code", "کد"}
TITLE_HEADERS = {"title", "name", "شرح کالا", "نام کالا", "شرح", "نام", "عنوان", "کالا"}
PRICE_HEADERS = {"price", "قیمت", "فی"}
MAX_TITLE = 300


def _norm_header(h) -> str:
    return " ".join(str(h or "").replace("﻿", "").replace("‌", " ").split()).lower()


def read_rows(name: str, data: bytes) -> list[list]:
    """CSV (UTF-8, with or without BOM; Windows-1256 as fallback) or .xlsx -> list of rows."""
    if name.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        except Exception:
            raise DomainError("unreadable_file", "Not a valid .xlsx file")
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if not name.lower().endswith((".csv", ".txt")):
        raise DomainError("unsupported_file_type", "Use .csv or .xlsx")
    for enc in ("utf-8-sig", "cp1256"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DomainError("unreadable_file", "Unknown text encoding")
    return list(csv.reader(io.StringIO(text)))


@dataclass
class Plan:
    rows_total: int = 0
    items: dict = field(default_factory=dict)  # (code, title) -> (barcode, price)
    errors: list = field(default_factory=list)  # [{"row": n, "code": "..."}]
    duplicate_rows: int = 0


def parse(rows: list[list]) -> Plan:
    if not rows:
        raise DomainError("empty_file", "The file is empty")
    header = [_norm_header(h) for h in rows[0]]

    def col(names):
        return next((i for i, h in enumerate(header) if h in names), None)

    ib, it, ip = col(BARCODE_HEADERS), col(TITLE_HEADERS), col(PRICE_HEADERS)
    if ib is None or it is None:
        raise DomainError("missing_columns", "Needs barcode and title columns", data={"headers": rows[0]})
    plan = Plan(rows_total=len(rows) - 1)
    for n, r in enumerate(rows[1:], start=2):
        get = lambda i: (r[i] if i is not None and i < len(r) else None)  # noqa: E731
        raw_bc, title = get(ib), " ".join(str(get(it) or "").split())
        barcode = clean(str(raw_bc) if raw_bc is not None else "")
        if not barcode and not title:
            continue  # blank line
        if not barcode or len(barcode) > 64:
            plan.errors.append({"row": n, "code": "invalid_barcode"})
            continue
        if not title:
            plan.errors.append({"row": n, "code": "title_required", "barcode": barcode})
            continue
        try:
            price = parse_price(get(ip)) if ip is not None else None
        except ValueError:
            price = None
            plan.errors.append({"row": n, "code": "invalid_price", "barcode": barcode})
        key = (canonical(barcode), title[:MAX_TITLE])
        if key in plan.items:
            plan.duplicate_rows += 1
        plan.items[key] = (barcode, price)  # the last row wins
    return plan


def _same_price(a: Decimal | None, b: Decimal | None) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and Decimal(a) == Decimal(b))


@transaction.atomic
def apply(plan: Plan, mode: str, user, *, dry_run: bool) -> dict:
    existing = {(m.code, m.title): m for m in MasterItem.objects.filter(deleted=False).only("id", "code", "title", "barcode", "price", "source")}
    new, changed = [], []
    for key, (barcode, price) in plan.items.items():
        m = existing.get(key)
        if m is None:
            new.append(MasterItem(code=key[0], title=key[1], barcode=barcode, price=price, source=MasterSource.IMPORT, created_by=user))
        elif not _same_price(m.price, price) or m.barcode != barcode:
            m.price, m.barcode = price, barcode
            changed.append(m)
    removed = []
    if mode == "replace":
        removed = [m for k, m in existing.items() if m.source == MasterSource.IMPORT and k not in plan.items]
    summary = {
        "rows": plan.rows_total, "items": len(plan.items), "new": len(new), "updated": len(changed),
        "unchanged": len(plan.items) - len(new) - len(changed), "removed": len(removed),
        "duplicate_rows": plan.duplicate_rows, "errors": len(plan.errors), "error_rows": plan.errors[:200],
        "barcodes_with_several_titles": _multi_title_count(plan),
    }
    if dry_run:
        return summary
    now = timezone.now()
    MasterItem.objects.bulk_create(new, batch_size=5000)
    for m in changed:
        m.updated_at = now
    MasterItem.objects.bulk_update(changed, ["price", "barcode", "updated_at"], batch_size=5000)
    if removed:
        ids = [m.pk for m in removed]
        for i in range(0, len(ids), 5000):
            MasterItem.objects.filter(pk__in=ids[i:i + 5000]).update(deleted=True, updated_at=now)
    return summary


def _multi_title_count(plan: Plan) -> int:
    seen: dict[str, int] = {}
    for code, _t in plan.items:
        seen[code] = seen.get(code, 0) + 1
    return sum(1 for n in seen.values() if n > 1)


def ensure_counter_title(barcode: str, title: str, user) -> None:
    """A title typed on the PDA joins the master (marked as counter-added) unless that
    barcode+title already exists or was deliberately deleted in the panel."""
    title = " ".join(title.split())[:MAX_TITLE]
    if not title:
        return
    code = canonical(barcode)
    if MasterItem.objects.filter(code=code, title=title).exists():
        return
    MasterItem.objects.create(code=code, title=title, barcode=barcode, source=MasterSource.COUNTER, created_by=user)
