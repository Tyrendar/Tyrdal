from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.errors import DomainError
from apps.accounts.permissions import require
from apps.audit.services import record

from .models import Barcode, BarcodeSource, Product
from .normalize import canonical, clean, normalize_text
from .services import MapResult, map_barcode


def _barcode_row(b: Barcode) -> dict:
    return {"id": b.pk, "barcode": b.raw, "code": b.code, "product_id": b.product_id, "source": b.source,
            "is_derived": b.is_derived, "is_active": b.is_active, "created_at": b.created_at,
            "deactivated_at": b.deactivated_at}


class ProductViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_permissions(self):
        if self.action in ("add_barcode", "deactivate_barcode"):
            return [require("barcodes.manage")()]
        return [require()()]

    def get_queryset(self):
        qs = Product.objects.all().order_by("id")
        q = self.request.query_params.get("q")
        if q:
            code = canonical(q)
            qs = qs.filter(
                Q(pk=clean(q)) | Q(title_normalized__icontains=normalize_text(q)) | Q(barcodes__code=code)
            ).distinct()
        return qs

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([{"id": p.id, "title": p.title, "title_en": p.title_en} for p in page])

    def retrieve(self, request, pk=None):
        p = get_object_or_404(Product, pk=pk)
        return Response({"id": p.id, "title": p.title, "title_en": p.title_en,
                         "barcodes": [_barcode_row(b) for b in p.barcodes.order_by("-is_active", "-created_at")]})

    @action(detail=True, methods=["post"], url_path="barcodes")
    def add_barcode(self, request, pk=None):
        p = get_object_or_404(Product, pk=pk)
        raw = clean(request.data.get("barcode") or "")
        if len(raw) < 4:
            raise DomainError("invalid_barcode")
        with transaction.atomic():
            result, bc = map_barcode(p, canonical(raw), raw, source=BarcodeSource.MANUAL,
                                     replace=bool(request.data.get("replace")), user=request.user)
            if result == MapResult.CONFLICT:
                raise DomainError("barcode_owned_by_other_product", data={"product_id": bc.product_id}, http_status=409)
            record("barcode.mapped", bc, request=request, after={"product_id": p.pk, "barcode": raw, "result": result.value})
        return Response(_barcode_row(bc))

    @action(detail=False, methods=["post"], url_path=r"barcodes/(?P<barcode_id>\d+)/deactivate")
    def deactivate_barcode(self, request, barcode_id=None):
        bc = get_object_or_404(Barcode, pk=barcode_id, is_active=True)
        bc.is_active = False
        bc.deactivated_at = timezone.now()
        bc.deactivated_by = request.user
        bc.save(update_fields=["is_active", "deactivated_at", "deactivated_by"])
        record("barcode.deactivated", bc, request=request, before={"product_id": bc.product_id, "barcode": bc.raw})
        return Response(_barcode_row(bc))
