"""Excel import for orders and for the central barcode mapping.

Two steps, so a supervisor always sees what will happen before anything changes:

1. validate_*_batch(batch): read the file, store every row verbatim
   (ImportRow), attach errors/warnings, compute a preview.
2. commit_*_batch(batch, user): re-check against the current database and apply
   in one transaction.

Errors and warnings are dicts with a stable `code` the UI translates.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import jdatetime
import openpyxl
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.catalog.models import Barcode, BarcodeSource, Product
from apps.catalog.normalize import BarcodeCheck, inspect_import_barcode, normalize_text

from .models import (
    Customer, ImportBatch, ImportKind, ImportProfile, ImportRow, ImportStatus, Order, OrderLine,
    OrderLineBarcode, OrderStatus,
)
from .services import recompute_order_counters

TEHRAN = ZoneInfo(settings.TIME_ZONE)
MAX_ROWS = 300_000
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_INT_RE = re.compile(r"^-?\d+(\.0+)?$")


class FileProblem(Exception):
    def __init__(self, code: str, **data):
        super().__init__(code)
        self.payload = {"code": code, **data}


# --- Reading ----------------------------------------------------------------
def sha256_of(fileobj) -> str:
    h = hashlib.sha256()
    fileobj.seek(0)
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        h.update(chunk)
    fileobj.seek(0)
    return h.hexdigest()


def _header(v) -> str:
    return re.sub(r"\s+", "_", str(v).strip().lower()) if v not in (None, "") else ""


def _jsonable(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    s = str(v)
    return s if s.strip() != "" else None


def read_sheet(fileobj) -> tuple[list[str], list[tuple[int, dict]]]:
    """Return normalized headers and (excel_row_number, {header: value}) for every non-empty row."""
    try:
        fileobj.seek(0)
        wb = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a user-facing file problem
        raise FileProblem("unreadable_file", detail=str(exc)[:200]) from exc
    try:
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers: list[str] | None = None
        header_row = 0
        for i, row in enumerate(it, start=1):
            if any(c not in (None, "") for c in row):
                headers = [_header(c) for c in row]
                header_row = i
                break
        if headers is None:
            raise FileProblem("empty_file")
        dupes = sorted({h for h in headers if h and headers.count(h) > 1})
        if dupes:
            raise FileProblem("duplicate_columns", columns=dupes)
        rows: list[tuple[int, dict]] = []
        for i, row in enumerate(it, start=header_row + 1):
            if not any(c not in (None, "") for c in row):
                continue
            rows.append((i, {h: _jsonable(v) for h, v in zip(headers, row) if h}))
            if len(rows) > MAX_ROWS:
                raise FileProblem("too_many_rows", limit=MAX_ROWS)
        return [h for h in headers if h], rows
    finally:
        wb.close()


# --- Value parsing ----------------------------------------------------------
@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str  # str | int | datetime
    required: bool = False
    positive: bool = False
    default: object = None


def parse_str(v):
    if v is None:
        return None, None
    s = str(v).strip()
    return (s or None), None


def parse_int(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    if isinstance(v, bool):
        return None, "not_integer"
    if isinstance(v, int):
        return v, None
    if isinstance(v, float):
        return (int(v), None) if v.is_integer() else (None, "not_integer")
    s = str(v).translate(_DIGITS).replace(",", "").replace("٬", "").strip()
    if _INT_RE.match(s):
        return int(float(s)) if "." in s else int(s), None
    return None, "not_integer"


_DT_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
               "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d")


def parse_datetime(v):
    """Naive values are warehouse local time (Asia/Tehran). Jalali dates (year < 1700) are accepted."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    s = str(v).translate(_DIGITS).strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = None
        for fmt in _DT_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None, "invalid_datetime"
    if dt.year < 1700:
        try:
            dt = jdatetime.datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second).togregorian()
        except ValueError:
            return None, "invalid_datetime"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TEHRAN)
    return dt, None


PARSERS = {"str": parse_str, "int": parse_int, "datetime": parse_datetime}


def _parse_fields(raw: dict, specs: list[FieldSpec], colmap: dict[str, str | None]):
    values, errors = {}, []
    for spec in specs:
        header = colmap.get(spec.name)
        v = raw.get(header) if header else None
        val, err = PARSERS[spec.kind](v)
        if err:
            errors.append({"code": err, "field": spec.name, "value": v})
            continue
        if val is None:
            val = spec.default
        if val is None and spec.required:
            errors.append({"code": "required", "field": spec.name})
        elif spec.positive and val is not None and val <= 0:
            errors.append({"code": "must_be_positive", "field": spec.name, "value": val})
        values[spec.name] = val
    return values, errors


def _resolve_columns(headers: list[str], specs: list[FieldSpec], profile: ImportProfile | None):
    """Map each field to a header, find barcode columns, list unmapped columns (kept as `extra`)."""
    cmap = {k: _header(v) for k, v in ((profile.column_map if profile else {}) or {}).items()}
    colmap: dict[str, str | None] = {}
    missing = []
    for spec in specs:
        h = cmap.get(spec.name, spec.name)
        colmap[spec.name] = h if h in headers else None
        if colmap[spec.name] is None and spec.required and spec.default is None:
            missing.append({"code": "missing_column", "field": spec.name, "header": h})
    pattern = re.compile(profile.barcode_column_pattern if profile else r"^barcode\d*$")
    mapped = {h for h in colmap.values() if h}
    barcode_cols = [h for h in headers if pattern.match(h) and h not in mapped]
    extra_cols = [h for h in headers if h not in mapped and h not in barcode_cols]
    return colmap, barcode_cols, extra_cols, missing


def _checking_cfg():
    cfg = settings.CHECKING
    return cfg["MIN_BARCODE_LENGTH"], frozenset(cfg["BARCODE_BLOCKLIST"])


def _barcode_checks(raw: dict, barcode_cols: list[str]) -> tuple[list[tuple[str, BarcodeCheck]], list[dict]]:
    min_len, blocklist = _checking_cfg()
    out, warnings = [], []
    for col in barcode_cols:
        v = raw.get(col)
        if v in (None, ""):
            continue
        chk = inspect_import_barcode(v, min_length=min_len, blocklist=blocklist)
        if chk.problem and not chk.code:
            warnings.append({"code": "barcode_unusable", "reason": chk.problem, "column": col, "value": str(v)})
            continue
        if chk.problem == "truncated_ean":
            warnings.append({"code": "barcode_truncated_ean", "column": col, "value": chk.raw,
                             "added": [d[1:] if len(d) == 14 and d.startswith("0") else d for d in chk.derived]})
        out.append((col, chk))
    return out, warnings


def _default_profile(kind: str) -> ImportProfile | None:
    return ImportProfile.objects.filter(kind=kind, is_default=True).first()


# --- Orders -----------------------------------------------------------------
ORDER_FIELDS = [
    FieldSpec("reference_id", "str", required=True),
    FieldSpec("reference_type", "str", required=True, default="Order"),
    FieldSpec("created_at", "datetime"),
    FieldSpec("customer", "str", required=True),
    FieldSpec("picker", "str"),
    FieldSpec("product_id", "str", required=True),
    FieldSpec("title", "str", required=True),
    FieldSpec("aisle_title", "str"),
    FieldSpec("aisle_rank", "int"),
    FieldSpec("pack_ordered", "int", required=True, positive=True),
    FieldSpec("inc_ordered", "int", required=True, positive=True),
    FieldSpec("units_ordered", "int", required=True, positive=True),
    FieldSpec("packs_picked", "int"),
    FieldSpec("units_picked", "int"),
    FieldSpec("physical_stock", "int"),
    FieldSpec("label", "str"),
]


class OrderAction:
    NEW = "new"
    UNCHANGED = "unchanged"
    INFO_UPDATED = "info_updated"  # same lines/quantities; picker or informational fields changed
    REPLACE = "replace"  # lines changed and checking has not started
    BLOCKED_STARTED = "blocked_started"
    BLOCKED_CLOSED = "blocked_closed"
    INVALID = "invalid"

    APPLIED = (NEW, INFO_UPDATED, REPLACE)


@dataclass
class RowResult:
    row_no: int
    raw: dict
    values: dict = field(default_factory=dict)
    barcodes: list[tuple[str, BarcodeCheck]] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def codes(self) -> list[tuple[str, str, bool]]:
        """(canonical code, raw, is_derived) for every usable barcode, deduplicated."""
        seen, out = set(), []
        for _col, chk in self.barcodes:
            for code, raw, derived in [(chk.code, chk.raw, False), *[(d, chk.raw, True) for d in chk.derived]]:
                if code not in seen:
                    seen.add(code)
                    out.append((code, raw, derived))
        return out


@dataclass
class OrderPlan:
    key: str
    rows: list[RowResult]
    reference_type: str = ""
    reference_id: str = ""
    customer: str = ""
    picker: str = ""
    created_at: datetime | None = None
    content_hash: str = ""
    action: str = OrderAction.NEW
    existing: Order | None = None

    @property
    def has_errors(self) -> bool:
        return any(r.errors for r in self.rows)

    def preview(self) -> dict:
        return {
            "key": self.key,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "customer": self.customer,
            "picker": self.picker,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "lines": len(self.rows),
            "boxes": sum((r.values.get("pack_ordered") or 0) for r in self.rows),
            "units": sum((r.values.get("units_ordered") or 0) for r in self.rows),
            "error_rows": sum(1 for r in self.rows if r.errors),
            "warning_rows": sum(1 for r in self.rows if r.warnings),
            "action": self.action,
            "existing_order_id": self.existing.pk if self.existing else None,
            "existing_status": self.existing.status if self.existing else None,
            "existing_version": self.existing.version if self.existing else None,
        }


def _drop_colliding_repairs(results: list[RowResult]) -> None:
    """A repaired (derived) barcode must never shadow a real barcode of another product.

    Real case: product 11596 lists "261182000552"; prefixing the dropped "6"
    gives 6261182000552, which is the genuine barcode of product 11590.
    Keeping it would count 11590's boxes on 11596.
    """
    real: dict[str, set[str]] = defaultdict(set)
    for rr in results:
        pid = rr.values.get("product_id")
        for _col, chk in rr.barcodes:
            if pid and chk.code:
                real[chk.code].add(pid)
    derived_codes = {d for rr in results for _c, chk in rr.barcodes for d in chk.derived}
    for code, pid in Barcode.objects.filter(code__in=list(derived_codes), is_active=True, is_derived=False).values_list("code", "product_id"):
        real[code].add(pid)
    for rr in results:
        pid = rr.values.get("product_id")
        fixed = []
        for col, chk in rr.barcodes:
            keep = []
            for d in chk.derived:
                others = real.get(d, set()) - {pid}
                if others:
                    rr.warnings.append({"code": "barcode_repair_skipped", "column": col, "value": chk.raw,
                                        "repair": d[1:] if len(d) == 14 and d.startswith("0") else d,
                                        "belongs_to": sorted(others)})
                else:
                    keep.append(d)
            if len(keep) != len(chk.derived):
                for w in rr.warnings:
                    if w["code"] == "barcode_truncated_ean" and w["column"] == col:
                        w["added"] = [k[1:] if len(k) == 14 and k.startswith("0") else k for k in keep]
            fixed.append((col, replace(chk, derived=tuple(keep))))
        rr.barcodes = fixed


def _order_hash(rows: list[RowResult]) -> str:
    lines = sorted(
        (r.values["product_id"], r.values["pack_ordered"], r.values["inc_ordered"], r.values["units_ordered"],
         sorted(c for c, _raw, _d in r.codes))
        for r in rows
    )
    return hashlib.sha256(json.dumps(lines, ensure_ascii=False).encode()).hexdigest()


def plan_orders(headers: list[str], raw_rows: list[tuple[int, dict]], profile: ImportProfile | None):
    """Validate rows and decide, per order, what committing would do. Reads the DB, writes nothing."""
    colmap, barcode_cols, extra_cols, missing = _resolve_columns(headers, ORDER_FIELDS, profile)
    if missing:
        return [], [], missing
    if not barcode_cols:
        return [], [], [{"code": "missing_column", "field": "barcode", "header": "barcode1"}]

    results: list[RowResult] = []
    for row_no, raw in raw_rows:
        rr = RowResult(row_no=row_no, raw=raw)
        rr.values, rr.errors = _parse_fields(raw, ORDER_FIELDS, colmap)
        rr.barcodes, rr.warnings = _barcode_checks(raw, barcode_cols)
        rr.extra = {h: raw.get(h) for h in extra_cols if raw.get(h) is not None}
        v = rr.values
        if not rr.errors and v["pack_ordered"] * v["inc_ordered"] != v["units_ordered"]:
            rr.errors.append({"code": "units_mismatch", "pack_ordered": v["pack_ordered"],
                              "inc_ordered": v["inc_ordered"], "units_ordered": v["units_ordered"],
                              "expected": v["pack_ordered"] * v["inc_ordered"]})
        results.append(rr)

    # Group into orders.
    groups: dict[str, list[RowResult]] = defaultdict(list)
    for rr in results:
        if rr.values.get("reference_id"):
            key = f"{rr.values.get('reference_type') or ''}|{rr.values['reference_id']}"
        else:
            key = "|"  # rows without a reference cannot belong to any order
        groups[key].append(rr)

    _drop_colliding_repairs(results)

    # Same barcode on two different products anywhere in the file.
    code_products: dict[str, set[str]] = defaultdict(set)
    for rr in results:
        for code, _raw, _d in rr.codes:
            if rr.values.get("product_id"):
                code_products[code].add(rr.values["product_id"])
    shared = {c: p for c, p in code_products.items() if len(p) > 1}

    # Central mapping state for every code in the file (one query).
    owners = dict(Barcode.objects.filter(code__in=list(code_products), is_active=True).values_list("code", "product_id"))

    plans: list[OrderPlan] = []
    for key, rows in groups.items():
        plan = OrderPlan(key=key, rows=rows)
        first = rows[0].values
        plan.reference_type = first.get("reference_type") or ""
        plan.reference_id = first.get("reference_id") or ""
        plan.customer = first.get("customer") or ""
        plan.created_at = first.get("created_at")
        pickers = sorted({r.values.get("picker") for r in rows if r.values.get("picker")})
        plan.picker = pickers[0] if pickers else ""
        seen_products: dict[str, int] = {}
        for r in rows:
            v = r.values
            for f in ("customer", "created_at"):
                if v.get(f) != first.get(f):
                    r.errors.append({"code": "order_header_mismatch", "field": f, "expected": str(first.get(f)), "value": str(v.get(f))})
            if len(pickers) > 1 and v.get("picker") and v.get("picker") != plan.picker:
                r.warnings.append({"code": "multiple_pickers", "pickers": pickers})
            pid = v.get("product_id")
            if pid:
                if pid in seen_products:
                    r.errors.append({"code": "duplicate_product_in_order", "product_id": pid, "first_row": seen_products[pid]})
                else:
                    seen_products[pid] = r.row_no
            for code, raw, _d in r.codes:
                if code in shared:
                    r.warnings.append({"code": "barcode_shared_in_file", "value": raw, "products": sorted(shared[code])})
                elif owners.get(code) and owners[code] != pid:
                    r.warnings.append({"code": "barcode_mapped_to_other_product", "value": raw, "product_id": owners[code]})
            if pid and not r.codes and not Barcode.objects.filter(product_id=pid, is_active=True).exists():
                r.warnings.append({"code": "no_usable_barcode", "product_id": pid})
        if key == "|":
            plan.action = OrderAction.INVALID
            plans.append(plan)
            continue
        if plan.has_errors:
            plan.action = OrderAction.INVALID
        else:
            plan.content_hash = _order_hash(rows)
            plan.existing = Order.objects.filter(reference_type=plan.reference_type, reference_id=plan.reference_id).first()
            plan.action = _classify(plan)
        plans.append(plan)
    return plans, results, []


def _classify(plan: OrderPlan) -> str:
    o = plan.existing
    if o is None:
        return OrderAction.NEW
    if o.content_hash == plan.content_hash:
        info_changed = (o.picker_name or "") != (plan.picker or "") or o.source_created_at != plan.created_at
        if not info_changed:
            existing = {l.product_id: l for l in o.lines.all()}
            for r in plan.rows:
                l = existing.get(r.values["product_id"])
                if l and _line_info(r) != (l.title, l.aisle_title, l.aisle_rank, l.packs_picked, l.units_picked, l.physical_stock, l.label):
                    info_changed = True
                    break
        return OrderAction.INFO_UPDATED if info_changed else OrderAction.UNCHANGED
    if o.status == OrderStatus.CANCELLED or o.status == OrderStatus.COMPLETED:
        return OrderAction.BLOCKED_CLOSED
    if o.status == OrderStatus.IN_PROGRESS or o.events.exists():
        return OrderAction.BLOCKED_STARTED
    return OrderAction.REPLACE


def _line_info(r: RowResult):
    v = r.values
    return (v["title"], v.get("aisle_title") or "", v.get("aisle_rank") or 0, v.get("packs_picked"),
            v.get("units_picked"), v.get("physical_stock"), v.get("label") or "")


def validate_order_batch(batch: ImportBatch) -> ImportBatch:
    batch.profile = batch.profile or _default_profile(ImportKind.ORDERS)
    try:
        with batch.file.open("rb") as f:
            headers, raw_rows = read_sheet(f)
    except FileProblem as p:
        batch.status = ImportStatus.FAILED
        batch.file_errors = [p.payload]
        batch.save()
        return batch
    plans, results, file_errors = plan_orders(headers, raw_rows, batch.profile)
    batch.file_errors = file_errors
    batch.preview = {"headers": headers, **_preview_from_plans(plans)}
    batch.rows_total = len(raw_rows)
    batch.rows.all().delete()
    if file_errors:
        ImportRow.objects.bulk_create(ImportRow(batch=batch, row_no=n, raw=raw) for n, raw in raw_rows)
        batch.status = ImportStatus.FAILED
    else:
        key_of = {id(r): p.key for p in plans for r in p.rows}
        ImportRow.objects.bulk_create(
            ImportRow(batch=batch, row_no=r.row_no, raw=r.raw, errors=r.errors, warnings=r.warnings, order_key=key_of.get(id(r), ""))
            for r in results
        )
        batch.rows_error = sum(1 for r in results if r.errors)
        batch.rows_warning = sum(1 for r in results if r.warnings)
    batch.save()
    return batch


def _preview_from_plans(plans: list[OrderPlan]) -> dict:
    orders = [p.preview() for p in plans]
    counts: dict[str, int] = defaultdict(int)
    for o in orders:
        counts[o["action"]] += 1
    return {"orders": orders, "actions": dict(counts), "importable": sum(1 for o in orders if o["action"] in OrderAction.APPLIED)}


@transaction.atomic
def commit_order_batch(batch: ImportBatch, user) -> ImportBatch:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != ImportStatus.VALIDATED:
        raise FileProblem("batch_not_committable", status=batch.status)
    if ImportBatch.objects.filter(file_sha256=batch.file_sha256, status=ImportStatus.COMMITTED).exists():
        raise FileProblem("duplicate_file")
    headers = batch.preview.get("headers") or []
    raw_rows = list(batch.rows.order_by("row_no").values_list("row_no", "raw"))
    plans, _results, file_errors = plan_orders(headers, raw_rows, batch.profile)
    if file_errors:
        raise FileProblem("file_invalid", errors=file_errors)

    applied = [p for p in plans if p.action in OrderAction.APPLIED]
    _ensure_products([r for p in applied for r in p.rows])
    mapping_conflicts = _add_order_barcodes_to_mapping([r for p in applied for r in p.rows], batch, user)

    summary: dict[str, list] = defaultdict(list)
    for plan in plans:
        summary[plan.action].append(plan.reference_id)
        if plan.action == OrderAction.NEW:
            order = Order.objects.create(
                reference_type=plan.reference_type, reference_id=plan.reference_id, content_hash=plan.content_hash,
                customer=_customer(plan.customer), picker_name=plan.picker, source_created_at=plan.created_at,
                import_batch=batch,
            )
            _create_lines(order, plan.rows)
            recompute_order_counters(order)
            record("order.imported", order, user=user, order=order, after={"batch": batch.pk, "lines": len(plan.rows)})
        elif plan.action == OrderAction.REPLACE:
            order = Order.objects.select_for_update().get(pk=plan.existing.pk)
            before = {"version": order.version, "content_hash": order.content_hash, "batch": order.import_batch_id,
                      "lines": order.lines.count()}
            order.lines.all().delete()
            order.version += 1
            order.content_hash = plan.content_hash
            order.customer = _customer(plan.customer)
            order.picker_name = plan.picker
            order.source_created_at = plan.created_at
            order.import_batch = batch
            order.save()
            _create_lines(order, plan.rows)
            recompute_order_counters(order)
            record("order.reimported", order, user=user, order=order, before=before,
                   after={"version": order.version, "batch": batch.pk, "lines": len(plan.rows)})
        elif plan.action == OrderAction.INFO_UPDATED:
            order = Order.objects.select_for_update().get(pk=plan.existing.pk)
            before = {"picker": order.picker_name}
            order.picker_name = plan.picker
            order.source_created_at = plan.created_at
            order.save(update_fields=["picker_name", "source_created_at"])
            lines = {l.product_id: l for l in order.lines.all()}
            changed = []
            for r in plan.rows:
                l = lines.get(r.values["product_id"])
                if not l:
                    continue
                (l.title, l.aisle_title, l.aisle_rank, l.packs_picked, l.units_picked, l.physical_stock, l.label) = _line_info(r)
                changed.append(l)
            OrderLine.objects.bulk_update(changed, ["title", "aisle_title", "aisle_rank", "packs_picked", "units_picked", "physical_stock", "label"])
            if plan.picker:
                order.discrepancies.filter(picker_name="").update(picker_name=plan.picker)
            record("order.info_updated", order, user=user, order=order, before=before, after={"picker": order.picker_name, "batch": batch.pk})

    batch.status = ImportStatus.COMMITTED
    batch.committed_by = user
    batch.committed_at = timezone.now()
    batch.result = {"orders": dict(summary), "mapping_conflicts": mapping_conflicts}
    batch.save()
    record("import.committed", batch, user=user, after=batch.result)
    return batch


def _customer(name: str) -> Customer:
    norm = normalize_text(name)
    c = Customer.objects.filter(name_normalized=norm).first()
    return c or Customer.objects.create(name=name)


def _ensure_products(rows: list[RowResult]) -> None:
    titles = {r.values["product_id"]: r.values["title"] for r in rows}
    existing = Product.objects.in_bulk(list(titles))
    new = [Product(id=pid, title=t, title_normalized=normalize_text(t)) for pid, t in titles.items() if pid not in existing]
    Product.objects.bulk_create(new, batch_size=1000)
    changed = []
    for pid, p in existing.items():
        if titles[pid] and p.title != titles[pid]:
            p.title = titles[pid]
            p.title_normalized = normalize_text(f"{p.title} {p.title_en}")
            changed.append(p)
    Product.objects.bulk_update(changed, ["title", "title_normalized"], batch_size=1000)


def _add_order_barcodes_to_mapping(rows: list[RowResult], batch, user) -> list[dict]:
    """Order-file barcodes also feed the central mapping, but never re-point a barcode that already belongs to another product."""
    wanted: dict[str, tuple[str, str, bool]] = {}
    for r in rows:
        for code, raw, derived in r.codes:
            wanted.setdefault(code, (r.values["product_id"], raw, derived))
    current = {b.code: b for b in Barcode.objects.filter(code__in=list(wanted), is_active=True)}
    conflicts, new, retired = [], [], []
    now = timezone.now()
    for code, (pid, raw, derived) in wanted.items():
        cur = current.get(code)
        if cur is not None and cur.product_id != pid and cur.is_derived and not derived:
            # A real barcode always beats an earlier guessed repair.
            cur.is_active, cur.deactivated_at, cur.deactivated_by = False, now, user
            retired.append(cur)
            cur = None
        if cur is None:
            new.append(Barcode(code=code, raw=raw, product_id=pid, source=BarcodeSource.ORDER_IMPORT,
                               is_derived=derived, import_batch=batch, created_by=user))
        elif cur.product_id != pid:
            conflicts.append({"barcode": raw, "file_product_id": pid, "mapped_product_id": cur.product_id})
    Barcode.objects.bulk_update(retired, ["is_active", "deactivated_at", "deactivated_by"])
    Barcode.objects.bulk_create(new, batch_size=1000)
    return conflicts


def _create_lines(order: Order, rows: list[RowResult]) -> None:
    lines = []
    for r in rows:
        v = r.values
        lines.append(OrderLine(
            order=order, product_id=v["product_id"], title=v["title"], aisle_title=v.get("aisle_title") or "",
            aisle_rank=v.get("aisle_rank") or 0, pack_ordered=v["pack_ordered"], inc_ordered=v["inc_ordered"],
            units_ordered=v["units_ordered"], packs_picked=v.get("packs_picked"), units_picked=v.get("units_picked"),
            physical_stock=v.get("physical_stock"), label=v.get("label") or "", extra=r.extra,
        ))
    created = OrderLine.objects.bulk_create(lines, batch_size=1000)
    if any(l.pk is None for l in created):  # backends without RETURNING
        by_product = {l.product_id: l for l in order.lines.all()}
        created = [by_product[l.product_id] for l in lines]
    codes = []
    for line, r in zip(created, rows):
        for code, raw, derived in r.codes:
            codes.append(OrderLineBarcode(order=order, line=line, code=code, raw=raw, is_derived=derived))
    OrderLineBarcode.objects.bulk_create(codes, batch_size=2000)


# --- Barcode mapping file ---------------------------------------------------
MAPPING_FIELDS = [
    FieldSpec("product_id", "str", required=True),
    FieldSpec("title", "str"),
]


class MappingAction:
    CREATE = "create"
    UNCHANGED = "unchanged"
    REPLACE = "replace"  # barcode moves from another product; old mapping kept as history


def plan_mapping(headers: list[str], raw_rows: list[tuple[int, dict]], profile: ImportProfile | None):
    colmap, barcode_cols, _extra, missing = _resolve_columns(headers, MAPPING_FIELDS, profile)
    if not barcode_cols:
        missing.append({"code": "missing_column", "field": "barcode", "header": "barcode"})
    if missing:
        return [], {}, missing
    results: list[RowResult] = []
    for row_no, raw in raw_rows:
        rr = RowResult(row_no=row_no, raw=raw)
        rr.values, rr.errors = _parse_fields(raw, MAPPING_FIELDS, colmap)
        rr.barcodes, rr.warnings = _barcode_checks(raw, barcode_cols)
        if not rr.errors and not rr.barcodes:
            rr.errors.append({"code": "no_usable_barcode"})
        results.append(rr)
    _drop_colliding_repairs(results)

    code_products: dict[str, set[str]] = defaultdict(set)
    for rr in results:
        if not rr.errors:
            for code, _raw, _d in rr.codes:
                code_products[code].add(rr.values["product_id"])
    for rr in results:
        for code, raw, _d in rr.codes:
            if len(code_products.get(code, ())) > 1:
                rr.errors.append({"code": "barcode_conflict_in_file", "value": raw, "products": sorted(code_products[code])})

    valid = [r for r in results if not r.errors]
    pids = {r.values["product_id"] for r in valid}
    known = set(Product.objects.filter(pk__in=pids).values_list("pk", flat=True))
    for r in valid:
        if r.values["product_id"] not in known and not r.values.get("title"):
            r.errors.append({"code": "title_required_for_new_product", "product_id": r.values["product_id"]})

    owners = dict(Barcode.objects.filter(code__in=list(code_products), is_active=True).values_list("code", "product_id"))
    actions: dict[str, int] = defaultdict(int)
    for r in results:
        if r.errors:
            continue
        for code, raw, _d in r.codes:
            owner = owners.get(code)
            if owner is None:
                actions[MappingAction.CREATE] += 1
            elif owner == r.values["product_id"]:
                actions[MappingAction.UNCHANGED] += 1
            else:
                actions[MappingAction.REPLACE] += 1
                r.warnings.append({"code": "barcode_will_move", "value": raw, "from_product_id": owner})
    return results, dict(actions), []


def validate_barcode_batch(batch: ImportBatch) -> ImportBatch:
    batch.profile = batch.profile or _default_profile(ImportKind.BARCODES)
    try:
        with batch.file.open("rb") as f:
            headers, raw_rows = read_sheet(f)
    except FileProblem as p:
        batch.status = ImportStatus.FAILED
        batch.file_errors = [p.payload]
        batch.save()
        return batch
    results, actions, file_errors = plan_mapping(headers, raw_rows, batch.profile)
    batch.rows.all().delete()
    batch.rows_total = len(raw_rows)
    batch.file_errors = file_errors
    if file_errors:
        batch.status = ImportStatus.FAILED
        ImportRow.objects.bulk_create(ImportRow(batch=batch, row_no=n, raw=raw) for n, raw in raw_rows)
    else:
        ImportRow.objects.bulk_create(
            (ImportRow(batch=batch, row_no=r.row_no, raw=r.raw, errors=r.errors, warnings=r.warnings) for r in results),
            batch_size=2000,
        )
        batch.rows_error = sum(1 for r in results if r.errors)
        batch.rows_warning = sum(1 for r in results if r.warnings)
    batch.preview = {"headers": headers, "actions": actions}
    batch.save()
    return batch


@transaction.atomic
def commit_barcode_batch(batch: ImportBatch, user) -> ImportBatch:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != ImportStatus.VALIDATED:
        raise FileProblem("batch_not_committable", status=batch.status)
    if ImportBatch.objects.filter(file_sha256=batch.file_sha256, status=ImportStatus.COMMITTED).exists():
        raise FileProblem("duplicate_file")
    headers = batch.preview.get("headers") or []
    raw_rows = list(batch.rows.order_by("row_no").values_list("row_no", "raw"))
    results, _actions, file_errors = plan_mapping(headers, raw_rows, batch.profile)
    if file_errors:
        raise FileProblem("file_invalid", errors=file_errors)
    valid = [r for r in results if not r.errors]
    # Only rows that carry a title may create/rename products.
    _ensure_products([r for r in valid if r.values.get("title")])

    wanted: dict[str, tuple[str, str, bool]] = {}
    for r in valid:
        for code, raw, derived in r.codes:
            wanted.setdefault(code, (r.values["product_id"], raw, derived))
    current = {b.code: b for b in Barcode.objects.filter(code__in=list(wanted), is_active=True)}
    now = timezone.now()
    to_deactivate, to_create = [], []
    counts = defaultdict(int)
    for code, (pid, raw, derived) in wanted.items():
        cur = current.get(code)
        if cur and cur.product_id == pid:
            counts[MappingAction.UNCHANGED] += 1
            continue
        if cur:
            cur.is_active, cur.deactivated_at, cur.deactivated_by = False, now, user
            to_deactivate.append(cur)
            counts[MappingAction.REPLACE] += 1
        else:
            counts[MappingAction.CREATE] += 1
        to_create.append(Barcode(code=code, raw=raw, product_id=pid, source=BarcodeSource.MAPPING_FILE,
                                 is_derived=derived, import_batch=batch, created_by=user))
    Barcode.objects.bulk_update(to_deactivate, ["is_active", "deactivated_at", "deactivated_by"], batch_size=1000)
    Barcode.objects.bulk_create(to_create, batch_size=1000)

    batch.status = ImportStatus.COMMITTED
    batch.committed_by = user
    batch.committed_at = now
    batch.result = {"actions": dict(counts), "rows_skipped": len(results) - len(valid)}
    batch.save()
    record("mapping.committed", batch, user=user, after=batch.result)
    return batch
