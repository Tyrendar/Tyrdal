"""Report calculations.

Definitions (all periods are warehouse-local dates, Asia/Tehran, `from`..`to` inclusive):

- An order is *checked* in the period when it was completed in the period.
- Volume (items/SKUs, boxes, discrepancies) is counted on orders completed in the period,
  so the same numbers appear in the overview, checker and picker reports.
- *Boxes scanned* counts accepted scan events in the period (work done, including on
  orders not finished yet). Double-reads are not boxes.
- *Active time* sums gaps between a checker's consecutive actions, ignoring gaps longer
  than CHECKING["ACTIVE_GAP_SECONDS"] (breaks, waiting for pallets). *Elapsed time* is
  first scan → completion.
- Discrepancies that resolved themselves (late boxes arrived) are not counted.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Avg, Count, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Role, User
from apps.checking.engine import active_gaps, active_seconds_of
from apps.checking.models import CheckEvent, Discrepancy, DiscrepancyStatus, EventKind, EventResult
from apps.orders.models import Assignment, Order, OrderStatus

TZ = ZoneInfo(settings.TIME_ZONE)
OPEN = (OrderStatus.PENDING_ASSIGNMENT, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS)
MAX_RANGE_DAYS = 400


@dataclass
class Period:
    start: datetime  # inclusive
    end: datetime  # exclusive
    date_from: date
    date_to: date

    def as_dict(self):
        return {"from": self.date_from.isoformat(), "to": self.date_to.isoformat()}


def parse_period(params) -> Period:
    today = timezone.localdate()
    d_from = parse_date(params.get("from") or "") or today
    d_to = parse_date(params.get("to") or "") or d_from
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > MAX_RANGE_DAYS:
        d_from = d_to - timedelta(days=MAX_RANGE_DAYS)
    start = datetime.combine(d_from, time.min, tzinfo=TZ)
    end = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=TZ)
    return Period(start, end, d_from, d_to)


def _completed(p: Period, checker: int | None = None, picker: str | None = None):
    qs = Order.objects.filter(status=OrderStatus.COMPLETED, completed_at__gte=p.start, completed_at__lt=p.end)
    if checker:
        qs = qs.filter(completed_by_id=checker)
    if picker is not None:
        qs = qs.filter(picker_name=picker)
    return qs


def ensure_active_seconds(orders) -> None:
    """Orders completed before active time was stored get it computed once."""
    for o in orders:
        if o.active_seconds is None and o.status == OrderStatus.COMPLETED:
            o.active_seconds = active_seconds_of(o.pk)
            Order.objects.filter(pk=o.pk).update(active_seconds=o.active_seconds)


def _live_discs(orders_qs):
    return Discrepancy.objects.filter(order__in=orders_qs, qty_boxes__gt=0).exclude(status=DiscrepancyStatus.RESOLVED)


def _counted_scans(p: Period):
    return CheckEvent.objects.filter(kind=EventKind.SCAN, result=EventResult.COUNTED, client_at__gte=p.start, client_at__lt=p.end)


def _ratio(a, b, digits=1):
    return round(a / b, digits) if b else None


# --- Overview ------------------------------------------------------------------
def overview(p: Period, checker: int | None = None) -> dict:
    done = _completed(p, checker)
    ensure_active_seconds(done.filter(active_seconds__isnull=True))
    agg = done.aggregate(
        orders=Count("id"),
        with_issues=Count("id", filter=Q(issues_total__gt=0)),
        skus=Sum("lines_total"),
        boxes_ordered=Sum("boxes_ordered"),
        boxes_checked=Sum("boxes_scanned"),
        active=Sum("active_seconds"),
        avg_active=Avg("active_seconds"),
    )
    elapsed = [(o.completed_at - o.first_scan_at).total_seconds() for o in done.exclude(first_scan_at=None).only("completed_at", "first_scan_at")]
    discs = _live_discs(done)
    by_type = {r["type"]: r for r in discs.values("type").annotate(lines=Count("id"), boxes=Sum("qty_boxes"), units=Sum("qty_units"))}

    assigned = Assignment.objects.filter(assigned_at__gte=p.start, assigned_at__lt=p.end)
    scans = _counted_scans(p)
    if checker:
        assigned = assigned.filter(checker_id=checker)
        scans = scans.filter(user_id=checker)

    active_assign = Assignment.objects.filter(revoked_at__isnull=True)
    now_qs = Order.objects.filter(status__in=OPEN)
    if checker:
        now_qs = now_qs.filter(pk__in=active_assign.filter(checker_id=checker).values("order_id"))
    now = {
        "waiting_assignment": now_qs.exclude(pk__in=active_assign.values("order_id")).count() if not checker else 0,
        "assigned_not_started": now_qs.filter(status=OrderStatus.ASSIGNED).count(),
        "in_progress": now_qs.filter(status=OrderStatus.IN_PROGRESS).count(),
        "unresolved_discrepancies": now_qs.filter(open_issues__gt=0).count(),
    }

    days = defaultdict(lambda: {"orders_completed": 0, "boxes_scanned": 0, "skus": 0})
    for r in done.annotate(d=TruncDate("completed_at", tzinfo=TZ)).values("d").annotate(n=Count("id"), skus=Sum("lines_total")):
        days[r["d"]]["orders_completed"] = r["n"]
        days[r["d"]]["skus"] = r["skus"] or 0
    for r in scans.annotate(d=TruncDate("client_at", tzinfo=TZ)).values("d").annotate(n=Count("id")):
        days[r["d"]]["boxes_scanned"] = r["n"]

    return {
        "period": p.as_dict(),
        "orders_assigned": assigned.values("order_id").distinct().count(),
        "orders_checked": agg["orders"],
        "orders_with_discrepancies": agg["with_issues"],
        "skus_checked": agg["skus"] or 0,
        "boxes_ordered": agg["boxes_ordered"] or 0,
        "boxes_checked": agg["boxes_checked"] or 0,
        "boxes_scanned": scans.count(),
        "discrepancies": discs.count(),
        "shortage_lines": by_type.get("short", {}).get("lines", 0),
        "shortage_boxes": by_type.get("short", {}).get("boxes", 0) or 0,
        "shortage_units": by_type.get("short", {}).get("units", 0) or 0,
        "extra_boxes": (by_type.get("extra", {}).get("boxes") or 0),
        "not_in_order_boxes": (by_type.get("not_in_order", {}).get("boxes") or 0),
        "avg_elapsed_seconds": int(sum(elapsed) / len(elapsed)) if elapsed else None,
        "avg_active_seconds": int(agg["avg_active"]) if agg["avg_active"] is not None else None,
        "avg_seconds_per_sku": _ratio(agg["active"] or 0, agg["skus"] or 0),
        "now": now,
        "by_day": [{"date": d.isoformat(), **v} for d, v in sorted(days.items())],
    }


# --- Checkers --------------------------------------------------------------------
def _user_active_seconds(p: Period, user_ids) -> dict[int, int]:
    rows = (CheckEvent.objects.filter(user_id__in=user_ids, client_at__gte=p.start, client_at__lt=p.end)
            .exclude(result__in=(EventResult.INVALID, EventResult.LOCKED))
            .order_by("user_id", "client_at").values_list("user_id", "client_at"))
    out: dict[int, list] = defaultdict(list)
    for uid, t in rows.iterator(chunk_size=5000):
        out[uid].append(t)
    return {uid: active_gaps(ts) for uid, ts in out.items()}


def checkers(p: Period, checker: int | None = None) -> dict:
    events = CheckEvent.objects.filter(client_at__gte=p.start, client_at__lt=p.end)
    if checker:
        events = events.filter(user_id=checker)
    ev = {r["user_id"]: r for r in events.values("user_id").annotate(
        boxes_scanned=Count("id", filter=Q(kind=EventKind.SCAN, result=EventResult.COUNTED)),
        double_reads=Count("id", filter=Q(kind=EventKind.SCAN, result=EventResult.DUPLICATE)),
        unknown_scans=Count("id", filter=Q(kind=EventKind.SCAN, result=EventResult.UNKNOWN)),
        mistakes=Count("id", filter=Q(kind=EventKind.EXTRA_DECISION, result=EventResult.MISTAKE)),
        corrections=Count("id", filter=Q(kind=EventKind.ADJUST, result=EventResult.APPLIED)),
    )}
    done = _completed(p, checker)
    ensure_active_seconds(done.filter(active_seconds__isnull=True))
    orders = {r["completed_by_id"]: r for r in done.values("completed_by_id").annotate(
        orders=Count("id"), skus=Sum("lines_total"), boxes_checked=Sum("boxes_scanned"),
        active=Sum("active_seconds"), with_issues=Count("id", filter=Q(issues_total__gt=0)),
    )}
    elapsed: dict[int, list] = defaultdict(list)
    for o in done.exclude(first_scan_at=None).only("completed_by_id", "completed_at", "first_scan_at"):
        elapsed[o.completed_by_id].append((o.completed_at - o.first_scan_at).total_seconds())
    discs: dict[int, dict] = defaultdict(dict)
    for r in _live_discs(done).values("order__completed_by_id", "type").annotate(lines=Count("id"), boxes=Sum("qty_boxes")):
        discs[r["order__completed_by_id"]][r["type"]] = r

    ids = set(ev) | {k for k in orders if k}
    active = _user_active_seconds(p, ids)
    users = {u.pk: u for u in User.objects.filter(pk__in=ids)}
    rows = []
    for uid in ids:
        u = users.get(uid)
        e, o, d = ev.get(uid, {}), orders.get(uid, {}), discs.get(uid, {})
        el = elapsed.get(uid, [])
        act = active.get(uid, 0)
        rows.append({
            "checker_id": uid,
            "name": u.display_name if u else str(uid),
            "username": u.username if u else "",
            "orders_checked": o.get("orders", 0),
            "orders_with_discrepancies": o.get("with_issues", 0),
            "skus_checked": o.get("skus") or 0,
            "boxes_checked": o.get("boxes_checked") or 0,
            "boxes_scanned": e.get("boxes_scanned", 0),
            "active_seconds": act,
            "boxes_per_hour": _ratio(e.get("boxes_scanned", 0) * 3600, act),
            "avg_elapsed_seconds": int(sum(el) / len(el)) if el else None,
            "avg_active_seconds": int((o.get("active") or 0) / o["orders"]) if o.get("orders") else None,
            "avg_seconds_per_sku": _ratio(o.get("active") or 0, o.get("skus") or 0),
            "shortage_lines": d.get("short", {}).get("lines", 0),
            "shortage_boxes": d.get("short", {}).get("boxes") or 0,
            "extra_boxes": d.get("extra", {}).get("boxes") or 0,
            "not_in_order_boxes": d.get("not_in_order", {}).get("boxes") or 0,
            "double_reads": e.get("double_reads", 0),
            "unknown_scans": e.get("unknown_scans", 0),
            "mistakes": e.get("mistakes", 0),
            "corrections": e.get("corrections", 0),
        })
    rows.sort(key=lambda r: (-r["boxes_scanned"], r["name"]))
    return {"period": p.as_dict(), "rows": rows}


# --- Pickers ---------------------------------------------------------------------
def pickers(p: Period) -> dict:
    done = _completed(p)
    base = {r["picker_name"]: r for r in done.values("picker_name").annotate(
        orders=Count("id"), skus=Sum("lines_total"), boxes_ordered=Sum("boxes_ordered"))}
    agg: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in _live_discs(done).values("order__picker_name", "type", "reason__category").annotate(lines=Count("id"), boxes=Sum("qty_boxes")):
        a = agg[r["order__picker_name"]]
        if r["type"] == "short":
            key = "short_stock" if r["reason__category"] == "stock" else "short_picking"
            a[f"{key}_lines"] += r["lines"]
            a[f"{key}_boxes"] += r["boxes"] or 0
        else:
            a[f"{r['type']}_boxes"] += r["boxes"] or 0
            a[f"{r['type']}_lines"] += r["lines"]
    rows = []
    for name, b in base.items():
        a = agg.get(name, {})
        errors = a.get("short_picking_boxes", 0) + a.get("extra_boxes", 0) + a.get("not_in_order_boxes", 0)
        rows.append({
            "picker": name or "",
            "orders": b["orders"], "skus": b["skus"] or 0, "boxes_ordered": b["boxes_ordered"] or 0,
            "short_stock_lines": a.get("short_stock_lines", 0), "short_stock_boxes": a.get("short_stock_boxes", 0),
            "short_picking_lines": a.get("short_picking_lines", 0), "short_picking_boxes": a.get("short_picking_boxes", 0),
            "extra_boxes": a.get("extra_boxes", 0), "not_in_order_boxes": a.get("not_in_order_boxes", 0),
            "not_in_order_lines": a.get("not_in_order_lines", 0),
            "error_boxes": errors,
            "error_rate_pct": _ratio(errors * 100, b["boxes_ordered"] or 0, 2),
        })
    rows.sort(key=lambda r: (-(r["error_boxes"]), r["picker"]))
    return {"period": p.as_dict(), "rows": rows}


# --- Reasons ---------------------------------------------------------------------
def reasons(p: Period, checker: int | None = None, picker: str | None = None) -> dict:
    discs = _live_discs(_completed(p, checker, picker))
    rows = [
        {"type": r["type"], "reason_id": r["reason_id"], "code": r["reason__code"], "name_fa": r["reason__name_fa"],
         "name_en": r["reason__name_en"], "category": r["reason__category"], "lines": r["lines"],
         "boxes": r["boxes"] or 0, "units": r["units"] or 0}
        for r in discs.values("type", "reason_id", "reason__code", "reason__name_fa", "reason__name_en", "reason__category")
        .annotate(lines=Count("id"), boxes=Sum("qty_boxes"), units=Sum("qty_units")).order_by("-boxes")
    ]
    return {"period": p.as_dict(), "rows": rows}


# --- Operations ------------------------------------------------------------------
def operations(p: Period, status: list[str] | None = None, checker: int | None = None, q: str = "") -> dict:
    """Orders active in the period (imported, scanned or completed in it) or still open, with timestamps."""
    in_period = (Q(imported_at__gte=p.start, imported_at__lt=p.end) | Q(first_scan_at__gte=p.start, first_scan_at__lt=p.end)
                 | Q(completed_at__gte=p.start, completed_at__lt=p.end) | Q(status__in=OPEN))
    qs = Order.objects.filter(in_period).select_related("customer", "completed_by")
    if status:
        qs = qs.filter(status__in=status)
    if checker:
        qs = qs.filter(Q(completed_by_id=checker) | Q(assignments__checker_id=checker, assignments__revoked_at__isnull=True)).distinct()
    if q:
        qs = qs.filter(Q(reference_id__icontains=q) | Q(customer__name__icontains=q) | Q(picker_name__icontains=q))
    qs = list(qs.order_by("-imported_at")[:2000])
    ensure_active_seconds([o for o in qs if o.status == OrderStatus.COMPLETED])
    active = {a.order_id: a for a in Assignment.objects.filter(order__in=qs, revoked_at__isnull=True).select_related("checker")}
    first_assigned = {r["order_id"]: r["t"] for r in Assignment.objects.filter(order__in=qs).values("order_id").annotate(t=Min("assigned_at"))}
    now = timezone.now()
    rows = []
    for o in qs:
        a = active.get(o.pk)
        end = o.completed_at or (now if o.status == OrderStatus.IN_PROGRESS else None)
        rows.append({
            "order_id": o.pk, "reference_id": o.reference_id, "customer": o.customer.name, "picker": o.picker_name,
            "status": o.status, "checker": (a.checker.display_name if a else None) or (o.completed_by.display_name if o.completed_by else None),
            "imported_at": o.imported_at, "assigned_at": first_assigned.get(o.pk), "started_at": o.first_scan_at,
            "completed_at": o.completed_at,
            "elapsed_seconds": int((end - o.first_scan_at).total_seconds()) if end and o.first_scan_at else None,
            "active_seconds": o.active_seconds,
            "wait_seconds": int((o.first_scan_at - first_assigned[o.pk]).total_seconds()) if o.first_scan_at and first_assigned.get(o.pk) else None,
            "skus": o.lines_total, "skus_done": o.lines_done, "boxes_ordered": o.boxes_ordered, "boxes_scanned": o.boxes_scanned,
            "discrepancies": o.issues_total, "open_discrepancies": o.open_issues,
        })
    return {"period": p.as_dict(), "rows": rows}

