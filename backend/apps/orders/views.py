from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.errors import DomainError
from apps.accounts.models import User
from apps.accounts.permissions import require
from apps.audit.models import AuditLog
from apps.checking.models import CheckEvent

from . import services
from .importing import (
    FileProblem, commit_barcode_batch, commit_order_batch, sha256_of, validate_barcode_batch, validate_order_batch,
)
from .models import Assignment, ImportBatch, ImportKind, ImportStatus, Order, OrderLine
from .serializers import ImportBatchSerializer, ImportRowSerializer, OrderDetailSerializer, OrderListSerializer


def _perm_for_kind(kind):
    return "barcodes.manage" if kind == ImportKind.BARCODES else "orders.import"


class ImportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Upload → preview (validated) → commit or discard."""

    serializer_class = ImportBatchSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        kind = None
        if self.action == "create":
            kind = self.request.data.get("kind") or ImportKind.ORDERS
        elif self.action in ("commit", "discard"):
            batch = ImportBatch.objects.filter(pk=self.kwargs.get("pk")).first()
            kind = batch.kind if batch else None
        if kind:
            return [require(_perm_for_kind(kind))()]
        return [require("orders.view")()]

    def get_queryset(self):
        qs = ImportBatch.objects.select_related("uploaded_by")
        if self.request.query_params.get("kind"):
            qs = qs.filter(kind=self.request.query_params["kind"])
        return qs

    def create(self, request):
        kind = request.data.get("kind") or ImportKind.ORDERS
        if kind not in ImportKind.values:
            raise DomainError("invalid_kind")
        f = request.FILES.get("file")
        if f is None:
            raise DomainError("file_required")
        if not f.name.lower().endswith((".xlsx", ".xlsm")):
            raise DomainError("unsupported_file_type", "Only .xlsx files are supported")
        digest = sha256_of(f)
        if ImportBatch.objects.filter(file_sha256=digest, status=ImportStatus.COMMITTED).exists():
            prev = ImportBatch.objects.filter(file_sha256=digest, status=ImportStatus.COMMITTED).first()
            raise DomainError("duplicate_file", "This exact file was already imported",
                              data={"batch_id": prev.pk, "committed_at": prev.committed_at}, http_status=409)
        batch = ImportBatch.objects.create(kind=kind, file=f, file_name=f.name, file_sha256=digest, uploaded_by=request.user)
        batch = validate_barcode_batch(batch) if kind == ImportKind.BARCODES else validate_order_batch(batch)
        return Response(ImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def rows(self, request, pk=None):
        batch = self.get_object()
        qs = batch.rows.all()
        f = request.query_params.get("filter")
        if f == "errors":
            qs = qs.exclude(errors=[])
        elif f == "warnings":
            qs = qs.exclude(warnings=[])
        elif f == "problems":
            qs = qs.exclude(errors=[], warnings=[])
        if request.query_params.get("order_key"):
            qs = qs.filter(order_key=request.query_params["order_key"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(ImportRowSerializer(page, many=True).data)

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        batch = get_object_or_404(ImportBatch, pk=pk)
        try:
            batch = commit_barcode_batch(batch, request.user) if batch.kind == ImportKind.BARCODES else commit_order_batch(batch, request.user)
        except FileProblem as p:
            raise DomainError(p.payload["code"], data=p.payload, http_status=409)
        return Response(ImportBatchSerializer(batch).data)

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        batch = get_object_or_404(ImportBatch, pk=pk)
        if batch.status != ImportStatus.VALIDATED:
            raise DomainError("batch_not_discardable", http_status=409)
        batch.status = ImportStatus.DISCARDED
        batch.save(update_fields=["status"])
        return Response(ImportBatchSerializer(batch).data)


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_permissions(self):
        perm = {
            "assign": "orders.assign", "reassign": "orders.assign", "unassign": "orders.assign",
            "cancel": "orders.manage", "reopen": "orders.manage", "audit": "audit.view",
        }.get(self.action, "orders.view")
        return [require(perm)()]

    def get_serializer_class(self):
        return OrderDetailSerializer if self.action == "retrieve" else OrderListSerializer

    def get_queryset(self):
        active = Prefetch("assignments", queryset=Assignment.objects.select_related("checker", "assigned_by", "revoked_by"))
        qs = Order.objects.select_related("customer", "completed_by").prefetch_related(active)
        if self.action == "retrieve":
            qs = qs.prefetch_related(Prefetch("lines", queryset=OrderLine.objects.prefetch_related("barcodes", "discrepancies__reason")))
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("checker"):
            qs = qs.filter(assignments__checker_id=p["checker"], assignments__revoked_at__isnull=True)
        if p.get("unassigned") == "true":
            qs = qs.exclude(pk__in=Assignment.objects.filter(revoked_at__isnull=True).values("order_id"))
        if p.get("has_issues") == "true":
            qs = qs.filter(issues_total__gt=0)
        if p.get("open_issues") == "true":
            qs = qs.filter(open_issues__gt=0)
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(reference_id__icontains=q) | Q(customer__name__icontains=q) | Q(picker_name__icontains=q))
        if p.get("from") and parse_date(p["from"]):
            qs = qs.filter(source_created_at__date__gte=parse_date(p["from"]))
        if p.get("to") and parse_date(p["to"]):
            qs = qs.filter(source_created_at__date__lte=parse_date(p["to"]))
        return qs.distinct()

    def _checker(self, request) -> User:
        checker = User.objects.filter(pk=request.data.get("checker_id")).first()
        if checker is None:
            raise DomainError("invalid_checker")
        return checker

    def _detail(self, order):
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        order = get_object_or_404(Order, pk=pk)
        services.assign(order, self._checker(request), by=request.user, request=request)
        return self._detail(order)

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        checker = self._checker(request)
        ids = request.data.get("order_ids") or []
        done, failed = [], []
        for order in Order.objects.filter(pk__in=ids):
            try:
                services.assign(order, checker, by=request.user, request=request)
                done.append(order.pk)
            except DomainError as e:
                failed.append({"order_id": order.pk, "code": e.error_code})
        return Response({"assigned": done, "failed": failed})

    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        order = get_object_or_404(Order, pk=pk)
        services.reassign(order, self._checker(request), by=request.user, reason=request.data.get("reason", ""), request=request)
        return self._detail(order)

    @action(detail=True, methods=["post"])
    def unassign(self, request, pk=None):
        order = get_object_or_404(Order, pk=pk)
        services.unassign(order, by=request.user, reason=request.data.get("reason", ""), request=request)
        return self._detail(order)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = get_object_or_404(Order, pk=pk)
        services.cancel(order, by=request.user, note=request.data.get("note", ""), request=request)
        return self._detail(order)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        order = get_object_or_404(Order, pk=pk)
        services.reopen(order, by=request.user, note=request.data.get("note", ""), request=request)
        return self._detail(order)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Live operational board counters."""
        from django.utils import timezone

        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        active = Assignment.objects.filter(revoked_at__isnull=True).values("order_id")
        open_q = Order.objects.filter(status__in=("pending_assignment", "assigned", "in_progress"))
        return Response({
            "waiting_assignment": open_q.exclude(pk__in=active).count(),
            "assigned_not_started": Order.objects.filter(status="assigned").count(),
            "in_progress": Order.objects.filter(status="in_progress").count(),
            "open_issues": open_q.filter(open_issues__gt=0).count(),
            "completed_today": Order.objects.filter(status="completed", completed_at__gte=today).count(),
            "completed_with_issues_today": Order.objects.filter(status="completed", completed_at__gte=today, issues_total__gt=0).count(),
            "boxes_scanned_today": CheckEvent.objects.filter(kind="scan", result="counted", client_at__gte=today).count(),
            "server_time": timezone.now(),
        })

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        qs = CheckEvent.objects.filter(order_id=pk).select_related("user", "line").order_by("-client_at")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([
            {"id": str(e.pk), "kind": e.kind, "result": e.result, "barcode": e.barcode_raw, "line_id": e.line_id,
             "product_id": e.product_id, "title": e.line.title if e.line else None, "delta_boxes": e.delta_boxes,
             "user": e.user.display_name, "at": e.client_at, "received_at": e.received_at, "is_late": e.is_late,
             "payload": e.payload, "ref_event_id": str(e.ref_event_id) if e.ref_event_id else None}
            for e in page
        ])

    @action(detail=True, methods=["get"])
    def audit(self, request, pk=None):
        qs = AuditLog.objects.filter(order_id=pk).select_related("user")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([
            {"id": a.pk, "at": a.at, "user": a.user.display_name if a.user else None, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "before": a.before, "after": a.after, "note": a.note}
            for a in page
        ])
