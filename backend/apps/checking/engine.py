"""Checking engine: the authoritative rules for scans, extras, shortages and completion.

The PDA applies the same rules locally for instant feedback, then sends its
events here in batches. Every event has a client-generated UUID, so re-sending
a batch is harmless. Events for one order are processed under a row lock on
that order, so two devices can never interleave.

Rules (see docs/01-proposal.md §0):
- 1 scan = 1 box. A scan increments the line until it reaches pack_ordered.
- Scanner double-reads are detected on the PDA (monotonic clock, DEBOUNCE_MS)
  and arrive flagged `duplicate`; they are recorded but never counted.
- A scan beyond the ordered quantity, or of a product not in the order, is
  never counted. It becomes *pending* and the checker must answer:
  "removed" (recorded as an extra discrepancy, default reason) or "mistake".
  Further scans are rejected until the answer arrives.
- A shortage exists only once declared ("Not found" or at Finish). Late boxes
  scanned afterwards reduce it automatically.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.errors import DomainError
from apps.audit.services import record
from apps.catalog.models import Barcode, Product
from apps.catalog.normalize import canonical
from apps.orders.models import Assignment, LineState, Order, OrderLine, OrderLineBarcode, OrderStatus
from apps.orders.services import recompute_order_counters

from .models import (
    PENDING_RESULTS, CheckEvent, Discrepancy, DiscrepancyReason, DiscrepancyStatus, DiscrepancyType, EventKind,
    EventResult, ReasonDefaultFor,
)


@dataclass
class Ctx:
    order: Order
    user: object
    device: object
    assignment: Assignment | None
    is_late: bool
    touched_lines: set[int]


# --- Public API -------------------------------------------------------------
def process_events(order_id: int, user, events: list[dict], device=None, sent_at: str | None = None) -> dict:
    """Apply a batch of PDA events in order. Returns per-event results plus the current state of touched lines.

    `sent_at` is the PDA's clock when it sent the batch. The difference to the
    server clock is applied to every event time, so a PDA whose clock is wrong
    still produces correct timestamps for reports.
    """
    offset = _clock_offset(sent_at)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        results = []
        touched: set[int] = set()
        for raw in events:
            results.append(_process_one(order, user, device, raw, touched, offset))
        recompute_order_counters(order)
        lines = list(order.lines.filter(pk__in=touched).prefetch_related("discrepancies"))
    return {"results": results, "lines": lines, "order": order}


def finish(order_id: int, user, device=None, request=None) -> Order:
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status == OrderStatus.COMPLETED:
            return order
        if order.status == OrderStatus.CANCELLED:
            raise DomainError("order_locked", "Order is cancelled", http_status=409)
        assignment = order.assignments.filter(revoked_at__isnull=True).first()
        if not assignment or assignment.checker_id != user.pk:
            raise DomainError("not_assigned", "Order is not assigned to you", http_status=403)
        problems = completion_problems(order)
        if problems:
            raise DomainError("cannot_complete", "Order is not ready to complete", data={"problems": problems}, http_status=409)
        order.status = OrderStatus.COMPLETED
        order.completed_at = timezone.now()
        order.completed_by = user
        order.active_seconds = active_seconds_of(order.pk)
        order.save(update_fields=["status", "completed_at", "completed_by", "active_seconds"])
        recompute_order_counters(order)
        record("order.completed", order, user=user, order=order, device=device, request=request,
               after={"boxes_scanned": order.boxes_scanned, "boxes_ordered": order.boxes_ordered,
                      "issues": order.issues_total})
    return order


def active_gaps(times, max_gap: int | None = None) -> int:
    """Seconds of activity in a sorted sequence of timestamps; gaps longer than max_gap are breaks."""
    from django.conf import settings

    limit = settings.CHECKING["ACTIVE_GAP_SECONDS"] if max_gap is None else max_gap
    total, prev = 0.0, None
    for t in times:
        if prev is not None:
            gap = (t - prev).total_seconds()
            if 0 < gap <= limit:
                total += gap
        prev = t
    return int(total)


def active_seconds_of(order_id: int) -> int:
    times = (CheckEvent.objects.filter(order_id=order_id)
             .exclude(result__in=(EventResult.INVALID, EventResult.LOCKED))
             .order_by("client_at").values_list("client_at", flat=True))
    return active_gaps(times.iterator())


def completion_problems(order: Order) -> list[dict]:
    problems = []
    pending = _pending_events(order)
    for ev in pending:
        problems.append({"code": "pending_decision", "event_id": str(ev.pk), "line_id": ev.line_id})
    lines = order.lines.filter(is_unordered=False).prefetch_related("discrepancies")
    for line in lines:
        if line.state in (LineState.PENDING, LineState.PARTIAL):
            problems.append({"code": "line_not_checked", "line_id": line.pk, "remaining": line.boxes_short})
    for d in order.discrepancies.exclude(status=DiscrepancyStatus.RESOLVED).select_related("reason"):
        if d.status == DiscrepancyStatus.OPEN:
            problems.append({"code": "discrepancy_without_reason", "line_id": d.line_id, "discrepancy_id": d.pk})
    return problems


# --- Dispatch ---------------------------------------------------------------
def _parse_time(value) -> datetime | None:
    when = parse_datetime(value) if isinstance(value, str) else None
    if when is not None and timezone.is_naive(when):
        when = timezone.make_aware(when)
    return when


def _clock_offset(sent_at: str | None) -> timedelta:
    sent = _parse_time(sent_at)
    return (timezone.now() - sent) if sent else timedelta(0)


def _parse_event(raw: dict, offset: timedelta) -> tuple[uuid.UUID | None, str, datetime]:
    try:
        eid = uuid.UUID(str(raw.get("id")))
    except (ValueError, TypeError):
        eid = None
    when = _parse_time(raw.get("at"))
    now = timezone.now()
    when = now if when is None else when + offset
    # Never in the future (only possible when the PDA sent no sent_at).
    return eid, str(raw.get("kind") or ""), min(when, now)


def _process_one(order: Order, user, device, raw: dict, touched: set[int], offset: timedelta) -> dict:
    eid, kind, at = _parse_event(raw, offset)
    if eid is None:
        return {"id": raw.get("id"), "result": EventResult.INVALID, "error": "invalid_id"}
    existing = CheckEvent.objects.filter(pk=eid).first()
    if existing:
        if existing.order_id != order.pk:
            return {"id": str(eid), "result": EventResult.INVALID, "error": "id_reused"}
        return _result(existing, replay=True)
    if kind not in EventKind.values:
        return {"id": str(eid), "result": EventResult.INVALID, "error": "unknown_kind"}

    assignment, is_late = _assignment_for(order, user, at)
    if assignment is None:
        return {"id": str(eid), "result": EventResult.INVALID, "error": "not_assigned"}

    ctx = Ctx(order=order, user=user, device=device, assignment=assignment, is_late=is_late, touched_lines=touched)
    ev = CheckEvent(id=eid, order=order, user=user, device=device, assignment=assignment, kind=kind,
                    client_at=at, is_late=is_late, payload={k: v for k, v in raw.items() if k not in ("id", "kind", "at")})

    if order.is_locked:
        ev.result = EventResult.LOCKED
        ev.barcode_raw = str(raw.get("barcode") or "")[:128]
        ev.save()
        return _result(ev)

    handler = {
        EventKind.SCAN: _scan,
        EventKind.EXTRA_DECISION: _extra_decision,
        EventKind.DECLARE_SHORT: _declare_short,
        EventKind.SET_REASON: _set_reason,
        EventKind.ADJUST: _adjust,
    }[kind]
    error = handler(ctx, ev, raw)
    if error:
        ev.result = EventResult.INVALID
        ev.payload = {**ev.payload, "error": error}
    ev.save()
    if ev.result != EventResult.INVALID and ev.result != EventResult.LOCKED:
        _mark_started(order, at)
    out = _result(ev)
    if error:
        out["error"] = error
    return out


def _result(ev: CheckEvent, replay: bool = False) -> dict:
    out = {"id": str(ev.pk), "kind": ev.kind, "result": ev.result, "line_id": ev.line_id,
           "product_id": ev.product_id, "replay": replay}
    if ev.payload.get("error"):
        out["error"] = ev.payload["error"]
    return out


def _assignment_for(order: Order, user, at: datetime) -> tuple[Assignment | None, bool]:
    active = order.assignments.filter(revoked_at__isnull=True).first()
    if active and active.checker_id == user.pk:
        return active, False
    # Work done offline before a reassignment still physically happened.
    late = (
        order.assignments.filter(checker=user, revoked_at__isnull=False, assigned_at__lte=at, revoked_at__gte=at)
        .order_by("-revoked_at").first()
    )
    return (late, True) if late else (None, False)


def _mark_started(order: Order, at: datetime) -> None:
    fields = []
    if order.status == OrderStatus.ASSIGNED:
        order.status = OrderStatus.IN_PROGRESS
        fields.append("status")
    if order.first_scan_at is None or at < order.first_scan_at:
        order.first_scan_at = at
        fields.append("first_scan_at")
    if order.last_scan_at is None or at > order.last_scan_at:
        order.last_scan_at = at
        fields.append("last_scan_at")
    if fields:
        order.save(update_fields=fields)


def _pending_events(order: Order):
    return list(CheckEvent.objects.filter(order=order, result__in=PENDING_RESULTS).exclude(decisions__isnull=False))


# --- Barcode resolution ------------------------------------------------------
def resolve(order: Order, code: str) -> tuple[str, OrderLine | None, Product | None]:
    """Priority 1: barcodes from this order's file. 2: central mapping. Returns (source, line, product)."""
    if not code:
        return "", None, None
    matches = list(OrderLineBarcode.objects.filter(order=order, code=code).values_list("line_id", "is_derived"))
    # A real barcode always wins over a repaired (derived) one.
    line_ids = [lid for lid, derived in matches if not derived] or [lid for lid, _d in matches]
    if line_ids:
        lines = list(OrderLine.objects.filter(pk__in=line_ids).order_by("aisle_rank", "id"))
        # Same barcode on two lines of one order: fill the first incomplete one.
        line = next((l for l in lines if l.boxes_scanned < l.pack_ordered), lines[0])
        return "order", line, line.product
    bc = Barcode.objects.select_related("product").filter(code=code, is_active=True).first()
    if bc:
        line = OrderLine.objects.filter(order=order, product=bc.product).first()
        return "mapping", line, bc.product
    return "", None, None


# --- Handlers (return an error code or None) ---------------------------------
def _scan(ctx: Ctx, ev: CheckEvent, raw: dict) -> str | None:
    barcode = str(raw.get("barcode") or "")
    ev.barcode_raw = barcode[:128]
    ev.barcode_code = canonical(barcode)[:64]
    if not ev.barcode_code:
        ev.result = EventResult.UNKNOWN
        return None

    # Scanner double-reads are detected on the PDA with its monotonic clock
    # (settings.CHECKING["DEBOUNCE_MS"]) and sent flagged, for the audit trail
    # and checker statistics. The server never re-decides this from wall-clock
    # times, so PDA and server counts cannot disagree.
    if raw.get("duplicate"):
        ev.result = EventResult.DUPLICATE
        _source, line, product = resolve(ctx.order, ev.barcode_code)
        ev.line, ev.product = line, product
        return None

    if _pending_events(ctx.order):
        ev.result = EventResult.BLOCKED
        return None

    source, line, product = resolve(ctx.order, ev.barcode_code)
    ev.match_source = source
    ev.product = product
    ev.line = line
    if product is None:
        ev.result = EventResult.UNKNOWN
        return None
    if line is None or line.is_unordered:
        ev.result = EventResult.NOT_IN_ORDER_PENDING
        return None
    line = OrderLine.objects.select_for_update().get(pk=line.pk)
    if line.boxes_scanned >= line.pack_ordered:
        ev.result = EventResult.OVER_PENDING
        return None
    line.boxes_scanned += 1
    line.last_scan_at = ev.client_at
    ev.delta_boxes = 1
    ev.result = EventResult.COUNTED
    _refresh_line(ctx, line)
    return None


def _extra_decision(ctx: Ctx, ev: CheckEvent, raw: dict) -> str | None:
    try:
        ref_id = uuid.UUID(str(raw.get("ref")))
    except (ValueError, TypeError):
        return "invalid_ref"
    decision = raw.get("decision")
    if decision not in ("removed", "mistake"):
        return "invalid_decision"
    ref = CheckEvent.objects.filter(pk=ref_id, order=ctx.order, result__in=PENDING_RESULTS).first()
    if ref is None:
        return "ref_not_pending"
    if ref.decisions.exists():
        return "already_decided"
    ev.ref_event = ref
    ev.product_id = ref.product_id
    ev.barcode_code = ref.barcode_code
    if decision == "mistake":
        ev.result = EventResult.MISTAKE
        ev.line_id = ref.line_id
        return None

    ev.result = EventResult.REMOVED
    if ref.result == EventResult.OVER_PENDING:
        line = OrderLine.objects.select_for_update().get(pk=ref.line_id)
        dtype, default_for = DiscrepancyType.EXTRA, ReasonDefaultFor.EXTRA
    else:
        line = _unordered_line(ctx.order, ref.product_id)
        dtype, default_for = DiscrepancyType.NOT_IN_ORDER, ReasonDefaultFor.NOT_IN_ORDER
    line.boxes_extra += 1
    ev.line = line
    d = _get_discrepancy(ctx, line, dtype)
    d.qty_boxes += 1
    d.qty_units = d.qty_boxes * line.inc_ordered
    if d.reason_id is None:
        d.reason = DiscrepancyReason.objects.filter(default_for=default_for, is_active=True).first()
    d.status = _status_for(d)
    d.save()
    _refresh_line(ctx, line)
    return None


def _declare_short(ctx: Ctx, ev: CheckEvent, raw: dict) -> str | None:
    line = _line_from(ctx, raw)
    if line is None:
        return "invalid_line"
    if line.is_unordered:
        return "line_not_ordered"
    if line.boxes_scanned >= line.pack_ordered:
        return "line_complete"
    reason, err = _reason_from(raw, DiscrepancyType.SHORT)
    if err:
        return err
    ev.line = line
    ev.product_id = line.product_id
    d = _get_discrepancy(ctx, line, DiscrepancyType.SHORT)
    before = _disc_snapshot(d)
    if reason is not None:
        d.reason = reason
    if "note" in raw:
        d.note = str(raw.get("note") or "")[:500]
    d.resolved_at = None
    d.status = DiscrepancyStatus.OPEN  # recomputed in _refresh_line
    d.save()
    ev.result = EventResult.APPLIED
    _refresh_line(ctx, line)
    _audit_disc(ctx, "discrepancy.declared", d, before)
    return None


def _set_reason(ctx: Ctx, ev: CheckEvent, raw: dict) -> str | None:
    line = _line_from(ctx, raw)
    if line is None:
        return "invalid_line"
    dtype = raw.get("type")
    if dtype not in DiscrepancyType.values:
        return "invalid_type"
    d = Discrepancy.objects.filter(line=line, type=dtype).first()
    if d is None or d.status == DiscrepancyStatus.RESOLVED:
        return "no_discrepancy"
    reason, err = _reason_from(raw, dtype, required=True)
    if err:
        return err
    before = _disc_snapshot(d)
    d.reason = reason
    if "note" in raw:
        d.note = str(raw.get("note") or "")[:500]
    d.status = _status_for(d)
    d.save()
    ev.line = line
    ev.product_id = line.product_id
    ev.result = EventResult.APPLIED
    ctx.touched_lines.add(line.pk)
    _audit_disc(ctx, "discrepancy.reason_set", d, before)
    return None


def _adjust(ctx: Ctx, ev: CheckEvent, raw: dict) -> str | None:
    """Checker corrects the counted boxes of a line (0..ordered). Always audited."""
    line = _line_from(ctx, raw)
    if line is None:
        return "invalid_line"
    if line.is_unordered:
        return "line_not_ordered"
    try:
        target = int(raw.get("boxes"))
    except (TypeError, ValueError):
        return "invalid_quantity"
    if target < 0 or target > line.pack_ordered:
        return "invalid_quantity"
    reason, err = _reason_from(raw, DiscrepancyType.SHORT, required=False, any_type=True)
    if err:
        return err
    before = line.boxes_scanned
    ev.delta_boxes = target - before
    line.boxes_scanned = target
    ev.line = line
    ev.product_id = line.product_id
    ev.result = EventResult.APPLIED
    ev.payload = {**ev.payload, "before": before}
    _refresh_line(ctx, line)
    record("line.adjusted", line, user=ctx.user, order=ctx.order, device=ctx.device,
           before={"boxes_scanned": before}, after={"boxes_scanned": target, "reason": reason.code if reason else None},
           note=str(raw.get("note") or ""))
    return None


# --- Helpers ----------------------------------------------------------------
def _line_from(ctx: Ctx, raw: dict) -> OrderLine | None:
    """Line by id; falls back to product_id for lines the PDA created offline (it has no server id yet)."""
    try:
        line_id = int(raw.get("line_id"))
    except (TypeError, ValueError):
        line_id = None
    if line_id is not None and line_id > 0:
        return OrderLine.objects.select_for_update().filter(pk=line_id, order=ctx.order).first()
    if raw.get("product_id"):
        return OrderLine.objects.select_for_update().filter(order=ctx.order, product_id=str(raw["product_id"])).first()
    return None


def _reason_from(raw: dict, dtype: str, required: bool = False, any_type: bool = False):
    rid = raw.get("reason_id")
    if rid in (None, ""):
        return None, ("reason_required" if required else None)
    reason = DiscrepancyReason.objects.filter(pk=rid, is_active=True).first()
    if reason is None:
        return None, "invalid_reason"
    if not any_type and not reason.applies(dtype):
        return None, "reason_not_applicable"
    return reason, None


def _get_discrepancy(ctx: Ctx, line: OrderLine, dtype: str) -> Discrepancy:
    d = Discrepancy.objects.select_for_update().filter(line=line, type=dtype).first()
    if d is None:
        d = Discrepancy(line=line, order=ctx.order, type=dtype, picker_name=ctx.order.picker_name, checker=ctx.user)
    else:
        d.checker = ctx.user
    return d


def _status_for(d: Discrepancy) -> str:
    if d.qty_boxes == 0:
        return DiscrepancyStatus.RESOLVED
    if d.reason_id is None:
        return DiscrepancyStatus.OPEN
    reason = d.reason
    if reason.requires_note and not d.note.strip():
        return DiscrepancyStatus.OPEN
    return DiscrepancyStatus.REASONED


def _refresh_line(ctx: Ctx, line: OrderLine) -> None:
    """Derive line state and keep its shortage record in step with the counted boxes."""
    short = Discrepancy.objects.select_for_update().filter(line=line, type=DiscrepancyType.SHORT).first()
    # An active (not resolved) shortage follows the counted boxes: late boxes
    # shrink it, and it resolves itself when the line is complete. A resolved
    # shortage stays closed; if boxes are later corrected down, the checker
    # declares a new one.
    if short is not None and not line.is_unordered and short.status != DiscrepancyStatus.RESOLVED:
        missing = max(line.pack_ordered - line.boxes_scanned, 0)
        short.qty_boxes = missing
        short.qty_units = missing * line.inc_ordered
        short.status = _status_for(short)
        if short.status == DiscrepancyStatus.RESOLVED:
            short.resolved_at = timezone.now()
        short.save()

    if line.is_unordered:
        line.state = LineState.EXTRA
    elif line.boxes_scanned >= line.pack_ordered:
        line.state = LineState.OK
    elif short is not None and short.status != DiscrepancyStatus.RESOLVED:
        line.state = LineState.SHORT
    elif line.boxes_scanned > 0:
        line.state = LineState.PARTIAL
    else:
        line.state = LineState.PENDING
    line.row_version += 1
    line.save()
    ctx.touched_lines.add(line.pk)


def _unordered_line(order: Order, product_id: str) -> OrderLine:
    line = OrderLine.objects.select_for_update().filter(order=order, product_id=product_id).first()
    if line:
        return line
    product = Product.objects.get(pk=product_id)
    # Units per box is unknown for a product that is not in the order; use the most recent known value.
    prev = OrderLine.objects.filter(product_id=product_id, is_unordered=False).order_by("-id").first()
    inc = prev.inc_ordered if prev else 0
    return OrderLine.objects.create(
        order=order, product=product, title=product.title, aisle_title=prev.aisle_title if prev else "",
        aisle_rank=prev.aisle_rank if prev else 0, pack_ordered=0, inc_ordered=inc, units_ordered=0,
        is_unordered=True, state=LineState.EXTRA,
    )


def _disc_snapshot(d: Discrepancy) -> dict | None:
    if d.pk is None:
        return None
    return {"qty_boxes": d.qty_boxes, "reason": d.reason_id, "note": d.note, "status": d.status}


def _audit_disc(ctx: Ctx, action: str, d: Discrepancy, before: dict | None) -> None:
    d.refresh_from_db()
    record(action, d, user=ctx.user, order=ctx.order, device=ctx.device, before=before, after=_disc_snapshot(d))
