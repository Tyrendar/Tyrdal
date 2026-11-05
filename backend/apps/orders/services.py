"""Supervisor-side order operations: assignment lifecycle, cancel, reopen, cached counters."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.errors import DomainError
from apps.accounts.models import Role
from apps.audit.services import record

from .models import Assignment, LineState, Order, OrderStatus


def recompute_order_counters(order: Order) -> Order:
    from apps.checking.models import CheckEvent, DiscrepancyStatus, DiscrepancyType, PENDING_RESULTS

    agg = order.lines.filter(is_unordered=False).aggregate(
        total=Count("id"),
        boxes_ordered=Sum("pack_ordered"),
        boxes_scanned=Sum("boxes_scanned"),
        ok=Count("id", filter=Q(state=LineState.OK)),
        short_reasoned=Count("id", filter=Q(state=LineState.SHORT, discrepancies__type=DiscrepancyType.SHORT,
                                            discrepancies__status=DiscrepancyStatus.REASONED)),
    )
    disc = order.discrepancies.aggregate(
        total=Count("id", filter=~Q(status=DiscrepancyStatus.RESOLVED)),
        open=Count("id", filter=Q(status=DiscrepancyStatus.OPEN)),
    )
    pending = (
        CheckEvent.objects.filter(order=order, result__in=PENDING_RESULTS)
        .exclude(decisions__isnull=False)
        .count()
    )
    order.lines_total = agg["total"] or 0
    order.boxes_ordered = agg["boxes_ordered"] or 0
    order.boxes_scanned = agg["boxes_scanned"] or 0
    order.lines_done = (agg["ok"] or 0) + (agg["short_reasoned"] or 0)
    order.issues_total = disc["total"] or 0
    order.open_issues = (disc["open"] or 0) + pending
    order.save(update_fields=["lines_total", "boxes_ordered", "boxes_scanned", "lines_done", "issues_total", "open_issues"])
    return order


def _lock(order_id: int) -> Order:
    return Order.objects.select_for_update().get(pk=order_id)


def _check_checker(checker):
    if checker.role != Role.CHECKER or not checker.is_active:
        raise DomainError("invalid_checker", "Target user is not an active checker")


@transaction.atomic
def assign(order: Order, checker, *, by, request=None) -> Assignment:
    order = _lock(order.pk)
    if order.is_locked:
        raise DomainError("order_locked", f"Order is {order.status}")
    _check_checker(checker)
    if order.assignments.filter(revoked_at__isnull=True).exists():
        raise DomainError("already_assigned", "Order already has an active checker; use reassign")
    a = Assignment.objects.create(order=order, checker=checker, assigned_by=by)
    if order.status == OrderStatus.PENDING_ASSIGNMENT:
        order.status = OrderStatus.ASSIGNED
        order.save(update_fields=["status"])
    record("order.assigned", a, user=by, order=order, after={"checker": checker.pk}, request=request)
    return a


@transaction.atomic
def reassign(order: Order, checker, *, by, reason: str = "", request=None) -> Assignment:
    order = _lock(order.pk)
    if order.is_locked:
        raise DomainError("order_locked", f"Order is {order.status}")
    _check_checker(checker)
    current = order.assignments.select_for_update().filter(revoked_at__isnull=True).first()
    if current and current.checker_id == checker.pk:
        raise DomainError("same_checker", "Order is already assigned to this checker")
    before = None
    if current:
        before = {"checker": current.checker_id, "assignment": current.pk}
        current.revoked_at = timezone.now()
        current.revoked_by = by
        current.revoke_reason = reason
        current.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    a = Assignment.objects.create(order=order, checker=checker, assigned_by=by)
    if order.status == OrderStatus.PENDING_ASSIGNMENT:
        order.status = OrderStatus.ASSIGNED
        order.save(update_fields=["status"])
    record("order.reassigned", a, user=by, order=order, before=before, after={"checker": checker.pk}, note=reason, request=request)
    return a


@transaction.atomic
def unassign(order: Order, *, by, reason: str = "", request=None) -> None:
    order = _lock(order.pk)
    if order.is_locked:
        raise DomainError("order_locked", f"Order is {order.status}")
    current = order.assignments.select_for_update().filter(revoked_at__isnull=True).first()
    if not current:
        raise DomainError("not_assigned", "Order has no active checker")
    current.revoked_at = timezone.now()
    current.revoked_by = by
    current.revoke_reason = reason
    current.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    if order.status == OrderStatus.ASSIGNED:
        order.status = OrderStatus.PENDING_ASSIGNMENT
        order.save(update_fields=["status"])
    record("order.unassigned", current, user=by, order=order, before={"checker": current.checker_id}, note=reason, request=request)


@transaction.atomic
def cancel(order: Order, *, by, note: str, request=None) -> Order:
    order = _lock(order.pk)
    if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        raise DomainError("order_locked", f"Order is {order.status}")
    if not note.strip():
        raise DomainError("note_required", "A note is required to cancel an order")
    before = order.status
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = by
    order.save(update_fields=["status", "cancelled_at", "cancelled_by"])
    order.assignments.filter(revoked_at__isnull=True).update(revoked_at=order.cancelled_at, revoked_by=by, revoke_reason="cancelled")
    record("order.cancelled", order, user=by, order=order, before={"status": before}, after={"status": order.status}, note=note, request=request)
    return order


@transaction.atomic
def reopen(order: Order, *, by, note: str, request=None) -> Order:
    order = _lock(order.pk)
    if order.status != OrderStatus.COMPLETED:
        raise DomainError("not_completed", "Only completed orders can be reopened")
    if not note.strip():
        raise DomainError("note_required", "A note is required to reopen an order")
    before = {"status": order.status, "completed_at": order.completed_at.isoformat(), "completed_by": order.completed_by_id}
    order.status = OrderStatus.IN_PROGRESS if order.assignments.filter(revoked_at__isnull=True).exists() else OrderStatus.PENDING_ASSIGNMENT
    order.completed_at = None
    order.completed_by = None
    order.save(update_fields=["status", "completed_at", "completed_by"])
    record("order.reopened", order, user=by, order=order, before=before, after={"status": order.status}, note=note, request=request)
    return order
