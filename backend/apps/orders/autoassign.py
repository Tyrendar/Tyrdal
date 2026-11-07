"""Capacity-based auto-assignment of orders to checkers.

Capacity is boxes per day (User.capacity_boxes). A checker's load today is the boxes
they scanned today plus the boxes still to scan on their open orders.

1. Targets: everyone should end the day at the same share of their capacity
   (water-filling): final_i = max(lambda * cap_i, load_i), with lambda chosen so the new
   orders are used up exactly. Up to total capacity lambda <= 1, so nobody goes over;
   beyond it the extra is spread in proportion to capacity.
2. Orders are not split: whole orders are packed to the targets, largest first, each to
   the checker with the biggest remaining gap, then improved by moving and swapping
   orders while that reduces the weighted squared distance to the targets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, F, Sum
from django.utils import timezone

from .models import Assignment, OrderStatus

MAX_SWAP_ORDERS = 400  # pairwise swaps are O(n^2); larger runs use moves only


def today_load(checker_ids) -> dict[int, int]:
    from apps.checking.models import CheckEvent, EventKind, EventResult

    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    done = dict(CheckEvent.objects.filter(user_id__in=checker_ids, kind=EventKind.SCAN, result=EventResult.COUNTED,
                                          client_at__gte=start).values("user_id").annotate(n=Count("id")).values_list("user_id", "n"))
    remaining = dict(Assignment.objects.filter(
        checker_id__in=checker_ids, revoked_at__isnull=True,
        order__status__in=(OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS),
    ).values("checker_id").annotate(r=Sum(F("order__boxes_ordered") - F("order__boxes_scanned"))).values_list("checker_id", "r"))
    return {c: int(done.get(c, 0) or 0) + max(int(remaining.get(c, 0) or 0), 0) for c in checker_ids}


@dataclass
class Checker:
    id: int
    capacity: int
    load: int
    target: float = 0.0  # boxes to give in this run
    orders: list = field(default_factory=list)  # [(order_id, boxes)]

    @property
    def assigned(self) -> int:
        return sum(b for _o, b in self.orders)


def _lambda(checkers: list[Checker], total: int) -> float:
    def given(lam):
        return sum(max(lam * c.capacity - c.load, 0) for c in checkers)

    lo, hi = 0.0, 1.0
    while given(hi) < total:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if given(mid) < total else (lo, mid)
    return hi


def _cost(c: Checker, assigned: int) -> float:
    return (assigned - c.target) ** 2 / c.capacity


def plan(orders: list[tuple[int, int]], checkers: list[Checker]) -> dict:
    """orders: [(order_id, boxes)]; checkers with capacity > 0. Returns the plan (nothing is saved)."""
    total = sum(b for _o, b in orders)
    lam = _lambda(checkers, total) if total else 0.0
    for c in checkers:
        c.target = max(lam * c.capacity - c.load, 0.0)
        c.orders = []

    # Largest orders first, each to the biggest remaining gap (ties: more capacity).
    for oid, boxes in sorted(orders, key=lambda o: (-o[1], o[0])):
        best = max(checkers, key=lambda c: (c.target - c.assigned - boxes / 2, c.capacity))
        best.orders.append((oid, boxes))

    _improve(checkers, swaps=len(orders) <= MAX_SWAP_ORDERS)
    return {"lambda": lam, "total": total}


def _improve(checkers: list[Checker], swaps: bool) -> None:
    for _ in range(50):
        improved = False
        sums = {c.id: c.assigned for c in checkers}
        # Moves: one order from i to k.
        for ci in checkers:
            for o in list(ci.orders):
                for ck in checkers:
                    if ck is ci:
                        continue
                    a, b = sums[ci.id], sums[ck.id]
                    delta = (_cost(ci, a - o[1]) + _cost(ck, b + o[1])) - (_cost(ci, a) + _cost(ck, b))
                    if delta < -1e-9:
                        ci.orders.remove(o)
                        ck.orders.append(o)
                        sums[ci.id], sums[ck.id] = a - o[1], b + o[1]
                        improved = True
                        break
        if swaps:
            # Swaps: order x of i with order y of k.
            for i, ci in enumerate(checkers):
                for ck in checkers[i + 1:]:
                    for x in list(ci.orders):
                        for y in list(ck.orders):
                            d = y[1] - x[1]
                            if d == 0 or x not in ci.orders or y not in ck.orders:
                                continue
                            a, b = sums[ci.id], sums[ck.id]
                            delta = (_cost(ci, a + d) + _cost(ck, b - d)) - (_cost(ci, a) + _cost(ck, b))
                            if delta < -1e-9:
                                ci.orders.remove(x); ck.orders.remove(y)  # noqa: E702
                                ci.orders.append(y); ck.orders.append(x)  # noqa: E702
                                sums[ci.id], sums[ck.id] = a + d, b - d
                                improved = True
        if not improved:
            return


def unassigned_orders(order_ids=None):
    """Open orders without an active checker (the same rule as the orders page's 'unassigned' filter)."""
    from .models import OPEN_STATUSES, Order

    qs = Order.objects.filter(status__in=OPEN_STATUSES).exclude(
        pk__in=Assignment.objects.filter(revoked_at__isnull=True).values("order_id"))
    if order_ids:
        qs = qs.filter(pk__in=order_ids)
    return qs
