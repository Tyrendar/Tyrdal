from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.errors import DomainError
from apps.accounts.models import Device
from apps.accounts.permissions import require, require_any
from apps.audit.services import record
from apps.catalog.models import Barcode
from apps.orders.models import Order, OrderLine, OrderStatus
from apps.orders.serializers import OrderLineSerializer

from . import engine
from .models import PENDING_RESULTS, CheckEvent, DiscrepancyReason


class ReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscrepancyReason
        fields = ["id", "code", "name_fa", "name_en", "applies_to", "category", "requires_note", "is_active",
                  "sort_order", "default_for"]


class ReasonViewSet(viewsets.ModelViewSet):
    serializer_class = ReasonSerializer
    http_method_names = ["get", "post", "patch", "put"]  # deactivate instead of delete

    def get_permissions(self):
        if self.request.method == "GET":
            return [require()()]
        return [require("reasons.manage")()]

    def get_queryset(self):
        qs = DiscrepancyReason.objects.all()
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        r = serializer.save()
        record("reason.created", r, request=self.request, after=ReasonSerializer(r).data)

    def perform_update(self, serializer):
        before = ReasonSerializer(serializer.instance).data
        r = serializer.save()
        record("reason.updated", r, request=self.request, before=before, after=ReasonSerializer(r).data)


# --- PDA ----------------------------------------------------------------------
def _device(request):
    serial = request.headers.get("X-Device-Serial")
    if not serial:
        return None
    device = Device.objects.filter(serial=serial).first()
    if device:
        Device.objects.filter(pk=device.pk).update(last_seen_at=timezone.now(), last_user=request.user)
    return device


def _my_order(request, order_id) -> Order:
    order = get_object_or_404(Order, pk=order_id)
    # Visible to the active checker, and to a previous checker only so their
    # offline events can still be delivered (engine decides what is accepted).
    if not order.assignments.filter(checker=request.user).exists():
        raise DomainError("not_assigned", "Order is not assigned to you", http_status=404)
    return order


def _order_summary(order: Order, user) -> dict:
    active = order.assignments.filter(revoked_at__isnull=True).first()
    return {
        "id": order.pk, "reference_id": order.reference_id, "reference_type": order.reference_type,
        "version": order.version, "customer": order.customer.name, "status": order.status,
        "lines_total": order.lines_total, "lines_done": order.lines_done, "boxes_ordered": order.boxes_ordered,
        "boxes_scanned": order.boxes_scanned, "open_issues": order.open_issues, "issues_total": order.issues_total,
        "is_mine": bool(active and active.checker_id == user.pk),
        "locked": order.is_locked,
    }


def _pending(order: Order) -> list[dict]:
    return [
        {"id": str(e.pk), "result": e.result, "line_id": e.line_id, "product_id": e.product_id,
         "barcode": e.barcode_raw, "at": e.client_at}
        for e in CheckEvent.objects.filter(order=order, result__in=PENDING_RESULTS).exclude(decisions__isnull=False)
    ]


class PdaOrdersView(APIView):
    """Orders assigned to the logged-in checker (active assignments only)."""

    permission_classes = [require("checking.perform")]

    def get(self, request):
        _device(request)
        qs = (Order.objects.filter(assignments__checker=request.user, assignments__revoked_at__isnull=True,
                                   status__in=(OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS))
              .select_related("customer").order_by("source_created_at", "id"))
        return Response([_order_summary(o, request.user) for o in qs])


class PdaOrderView(APIView):
    """Full snapshot of one order for offline checking: lines, their barcodes, discrepancies, pending decisions."""

    permission_classes = [require("checking.perform")]

    def get(self, request, order_id):
        order = _my_order(request, order_id)
        lines = OrderLine.objects.filter(order=order).prefetch_related("discrepancies__reason", "barcodes")
        # Canonical codes with the "derived" flag: the PDA resolves scans offline
        # with the same rule as the server (real barcodes beat repaired ones).
        line_codes = {}
        for line in lines:
            line_codes[line.pk] = [{"code": b.code, "derived": b.is_derived} for b in line.barcodes.all()]
        data = OrderLineSerializer(lines, many=True).data
        for row in data:
            row["codes"] = line_codes[row["id"]]
        return Response({
            "order": _order_summary(order, request.user),
            "lines": data,
            "pending": _pending(order),
            "server_time": timezone.now(),
        })


class PdaEventsView(APIView):
    permission_classes = [require("checking.perform")]

    def post(self, request, order_id):
        order = _my_order(request, order_id)
        events = request.data.get("events")
        if not isinstance(events, list) or not events:
            raise DomainError("events_required")
        if len(events) > 500:
            raise DomainError("too_many_events", data={"max": 500})
        out = engine.process_events(order.pk, request.user, events, device=_device(request),
                                    sent_at=request.data.get("sent_at"))
        return Response({
            "results": out["results"],
            "lines": OrderLineSerializer(out["lines"], many=True).data,
            "order": _order_summary(out["order"], request.user),
            "pending": _pending(out["order"]),
        })


class PdaFinishView(APIView):
    permission_classes = [require("checking.perform")]

    def post(self, request, order_id):
        order = _my_order(request, order_id)
        order = engine.finish(order.pk, request.user, device=_device(request), request=request)
        return Response({"order": _order_summary(order, request.user)})


class PdaFinishCheckView(APIView):
    """What still blocks completion (for the Finish screen)."""

    permission_classes = [require("checking.perform")]

    def get(self, request, order_id):
        order = _my_order(request, order_id)
        return Response({"problems": engine.completion_problems(order)})


class PdaBarcodesView(APIView):
    """Central barcode mapping for the PDA's local cache, as a change feed.

    ?since=<ISO time> returns rows created or deactivated after that time;
    without it, every active row. Paginated with ?after_id= for large catalogs.
    """

    permission_classes = [require_any("checking.perform", "stocktake.perform")]
    PAGE = 5000

    def get(self, request):
        since = parse_datetime(request.query_params.get("since") or "")
        after_id = int(request.query_params.get("after_id") or 0)
        qs = Barcode.objects.select_related("product").filter(pk__gt=after_id).order_by("pk")
        if since:
            qs = qs.filter(created_at__gt=since) | qs.filter(deactivated_at__gt=since)
            qs = qs.order_by("pk")
        else:
            qs = qs.filter(is_active=True)
        rows = list(qs[: self.PAGE])
        return Response({
            "server_time": timezone.now(),
            "has_more": len(rows) == self.PAGE,
            "next_after_id": rows[-1].pk if rows else after_id,
            "barcodes": [{"id": b.pk, "code": b.code, "product_id": b.product_id, "title": b.product.title,
                          "active": b.is_active} for b in rows],
        })


class PdaConfigView(APIView):
    permission_classes = [require("checking.perform")]

    def get(self, request):
        cfg = settings.CHECKING
        reasons = DiscrepancyReason.objects.filter(is_active=True)
        return Response({
            "debounce_ms": cfg["DEBOUNCE_MS"],
            "min_barcode_length": cfg["MIN_BARCODE_LENGTH"],
            "reasons": ReasonSerializer(reasons, many=True).data,
            "server_time": timezone.now(),
        })
