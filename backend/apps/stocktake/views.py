import io
from datetime import timedelta

import jdatetime
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.errors import DomainError
from apps.accounts.models import Role, RolePermission, User
from apps.accounts.permissions import require
from apps.audit.services import record
from apps.checking.views import _device
from apps.reports.services import TZ

from . import services
from .models import Stocktake, StockCount, StocktakeStatus, Vendor

PERFORM = "stocktake.perform"
MANAGE = "stocktake.manage"


def stocktakers():
    """Active users whose role may count stock on the PDA (admins hold every permission but are not counters)."""
    roles = set(RolePermission.objects.filter(permission=PERFORM).values_list("role", flat=True)) - {Role.ADMIN}
    return User.objects.filter(is_active=True, role__in=roles)


# --- Panel ----------------------------------------------------------------------------
class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "name", "code", "is_active", "created_at"]
        read_only_fields = ["created_at"]

    def validate_name(self, v):
        v = " ".join(v.split())
        if not v:
            raise serializers.ValidationError("required")
        return v


class VendorViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """No delete: a vendor with stocktakes is deactivated instead."""

    serializer_class = VendorSerializer
    permission_classes = [require(MANAGE)]
    pagination_class = None

    def get_queryset(self):
        qs = Vendor.objects.annotate(stocktakes_count=Count("stocktakes"))
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        v = serializer.save()
        record("vendor.created", v, request=self.request, after=VendorSerializer(v).data)

    def perform_update(self, serializer):
        before = VendorSerializer(serializer.instance).data
        v = serializer.save()
        record("vendor.updated", v, request=self.request, before=before, after=VendorSerializer(v).data)


class StocktakeWriteSerializer(serializers.ModelSerializer):
    vendor_id = serializers.PrimaryKeyRelatedField(source="vendor", queryset=Vendor.objects.filter(is_active=True))
    counter_ids = serializers.PrimaryKeyRelatedField(source="counters", many=True, queryset=User.objects.filter(is_active=True))

    class Meta:
        model = Stocktake
        fields = ["vendor_id", "date", "counter_ids", "note"]

    def validate_counter_ids(self, users):
        allowed = set(stocktakers().values_list("pk", flat=True))
        bad = [u.username for u in users if u.pk not in allowed]
        if bad:
            raise DomainError("invalid_counter", "Not a stocktaking user", data={"users": bad})
        return users


def _brief(st: Stocktake) -> dict:
    return {
        "id": st.pk, "vendor": {"id": st.vendor_id, "name": st.vendor.name, "code": st.vendor.code}, "date": st.date,
        "status": st.status, "note": st.note, "created_at": st.created_at, "closed_at": st.closed_at,
        "counters": [{"id": u.pk, "name": u.display_name, "username": u.username} for u in st.counters.all()],
        "records": getattr(st, "n_records", None), "quantity": getattr(st, "n_quantity", None),
        "barcodes": getattr(st, "n_barcodes", None),
    }


class StocktakeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                       mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [require(MANAGE)]

    def get_queryset(self):
        live = Q(counts__deleted=False)
        qs = (Stocktake.objects.select_related("vendor").prefetch_related("counters")
              .annotate(n_records=Count("counts", filter=live), n_quantity=Sum("counts__quantity", filter=live),
                        n_barcodes=Count("counts__code", filter=live, distinct=True)))
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if (p.get("vendor") or "").isdigit():
            qs = qs.filter(vendor_id=int(p["vendor"]))
        if parse_date(p.get("from") or ""):
            qs = qs.filter(date__gte=parse_date(p["from"]))
        if parse_date(p.get("to") or ""):
            qs = qs.filter(date__lte=parse_date(p["to"]))
        if p.get("q"):
            qs = qs.filter(Q(vendor__name__icontains=p["q"]) | Q(note__icontains=p["q"]))
        return qs.order_by("-date", "-id")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([_brief(s) for s in page])

    def retrieve(self, request, *args, **kwargs):
        st = self.get_object()
        tot = services.totals(st)
        return Response({
            **_brief(st),
            "countable": services.is_countable(st),
            "by_counter": services.counter_summary(st),
            "totals": {"barcodes": len(tot), "quantity": sum(t.quantity for t in tot), "records": sum(t.records for t in tot),
                       "price_conflicts": sum(1 for t in tot if len(t.prices) > 1),
                       "without_price": sum(1 for t in tot if t.price is None)},
        })

    def create(self, request, *args, **kwargs):
        s = StocktakeWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        st = s.save(created_by=request.user)
        record("stocktake.created", st, request=request, after={"vendor": st.vendor.name, "date": str(st.date),
                                                                  "counters": [u.username for u in st.counters.all()]})
        return Response(_brief(self.get_queryset().get(pk=st.pk)), status=201)

    def update(self, request, *args, **kwargs):
        st = self.get_object()
        if st.status == StocktakeStatus.CLOSED:
            raise DomainError("stocktake_closed", "Reopen it first", http_status=409)
        before = {"vendor": st.vendor.name, "date": str(st.date), "note": st.note, "counters": sorted(u.username for u in st.counters.all())}
        s = StocktakeWriteSerializer(st, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        st = s.save()
        record("stocktake.updated", st, request=request, before=before,
               after={"vendor": st.vendor.name, "date": str(st.date), "note": st.note, "counters": sorted(u.username for u in st.counters.all())})
        return Response(_brief(self.get_queryset().get(pk=st.pk)))

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        services.close(self.get_object(), request.user, request)
        return Response(_brief(self.get_queryset().get(pk=pk)))

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        services.reopen(self.get_object(), request.user, request)
        return Response(_brief(self.get_queryset().get(pk=pk)))

    @action(detail=True, methods=["get"])
    def records(self, request, pk=None):
        st = self.get_object()
        qs = st.counts.select_related("user", "product").order_by("-counted_at")
        p = request.query_params
        if p.get("deleted") != "true":
            qs = qs.filter(deleted=False)
        if (p.get("counter") or "").isdigit():
            qs = qs.filter(user_id=int(p["counter"]))
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(Q(barcode__icontains=q) | Q(code__icontains=q) | Q(product__title__icontains=q) | Q(product_id=q))
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([{
            "id": str(c.id), "user": c.user.display_name, "user_id": c.user_id, "barcode": c.barcode, "code": c.code,
            "product_id": c.product_id, "title": c.product.title if c.product else None, "quantity": c.quantity,
            "price": c.price, "counted_at": c.counted_at, "deleted": c.deleted,
        } for c in page])

    @action(detail=True, methods=["get"])
    def totals(self, request, pk=None):
        st = self.get_object()
        rows = [t.as_dict() for t in services.totals(st)]
        q = (request.query_params.get("q") or "").strip()
        if q:
            rows = [r for r in rows if q in r["barcode"] or q in r["code"] or q in (r["title"] or "")]
        if request.query_params.get("conflicts") == "true":
            rows = [r for r in rows if r["price_conflict"]]
        return Response(rows)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        st = self.get_object()
        kind = request.query_params.get("kind", "wms")
        lang = "en" if request.query_params.get("lang") == "en" else "fa"
        name = f"stocktake_{st.vendor.name}_{st.date}".replace(" ", "_")
        if kind == "detail":
            return _xlsx(_detail_workbook(st, lang), f"{name}_detail.xlsx")
        return _xlsx(_wms_workbook(st), f"{name}.xlsx")


class StocktakersView(APIView):
    """Users who can be assigned to stocktakes, with their open stocktakes."""

    permission_classes = [require(MANAGE)]

    def get(self, request):
        qs = stocktakers().annotate(open_stocktakes=Count("stocktakes", filter=Q(stocktakes__status=StocktakeStatus.OPEN)))
        return Response([{"id": u.pk, "username": u.username, "name": u.display_name, "open_stocktakes": u.open_stocktakes}
                         for u in qs.order_by("full_name", "username")])


# --- Excel ----------------------------------------------------------------------------
def _num(v):
    if v is None:
        return None
    return int(v) if v == int(v) else float(v)


def _xlsx(wb: Workbook, filename: str) -> HttpResponse:
    buf = io.BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ascii_name = filename.encode("ascii", "ignore").decode() or "stocktake.xlsx"
    from urllib.parse import quote

    resp["Content-Disposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return resp


def _wms_workbook(st: Stocktake) -> Workbook:
    """Exactly the WMS upload format: one sheet, columns barcode, count, price; one row per barcode."""
    wb = Workbook()
    ws = wb.active
    ws.title = "stocktake"
    ws.append(["barcode", "count", "price"])
    for t in services.totals(st):
        ws.append([t.barcode, t.quantity, _num(t.price)])
    for row in ws.iter_rows(min_row=2, max_col=1):
        row[0].number_format = "@"  # keep leading zeros / no scientific notation
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 16
    return wb


def _fmt_dt(v, lang):
    local = v.astimezone(TZ).replace(tzinfo=None)
    if lang == "fa":
        return jdatetime.datetime.fromgregorian(datetime=local).strftime("%Y/%m/%d %H:%M:%S")
    return local


def _sheet(ws, headers, rows, widths, lang):
    if lang == "fa":
        ws.sheet_view.rightToLeft = True
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0F766E")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def _detail_workbook(st: Stocktake, lang: str) -> Workbook:
    fa = lang == "fa"
    wb = Workbook()
    ws = wb.active
    ws.title = "Totals"
    tot = services.totals(st)
    _sheet(ws, ["بارکد", "کالا", "تعداد", "قیمت", "تعداد ثبت", "تعداد شمارنده", "قیمت متفاوت"] if fa
           else ["Barcode", "Product", "Count", "Price", "Records", "Counters", "Price conflict"],
           [[t.barcode, t.title or None, t.quantity, _num(t.price), t.records, len(t.counters),
             ("بله" if fa else "Yes") if len(t.prices) > 1 else None] for t in tot],
           [20, 40, 10, 14, 10, 12, 12], lang)
    for row in ws.iter_rows(min_row=2, max_col=1):
        row[0].number_format = "@"

    ws2 = wb.create_sheet("Records")
    counts = st.counts.filter(deleted=False).select_related("user", "product").order_by("user__username", "counted_at")
    _sheet(ws2, ["شمارنده", "زمان", "بارکد", "کالا", "تعداد", "قیمت"] if fa
           else ["Counter", "Time", "Barcode", "Product", "Count", "Price"],
           [[c.user.display_name, _fmt_dt(c.counted_at, lang), c.barcode, c.product.title if c.product else None,
             c.quantity, _num(c.price)] for c in counts.iterator(chunk_size=5000)],
           [18, 22, 20, 40, 10, 14], lang)
    for row in ws2.iter_rows(min_row=2, min_col=3, max_col=3):
        row[0].number_format = "@"
    if not fa:
        for row in ws2.iter_rows(min_row=2, min_col=2, max_col=2):
            row[0].number_format = "yyyy-mm-dd hh:mm:ss"
    return wb


# --- PDA ------------------------------------------------------------------------------
UPCOMING_DAYS = 7


def _my_stocktake(request, pk) -> Stocktake:
    st = get_object_or_404(Stocktake.objects.select_related("vendor"), pk=pk)
    if not st.counters.filter(pk=request.user.pk).exists():
        raise DomainError("not_a_counter", "You are not assigned to this stocktake", http_status=403)
    return st


def _pda_brief(st: Stocktake, user) -> dict:
    mine = st.counts.filter(user=user, deleted=False).aggregate(n=Count("id"), q=Sum("quantity"))
    return {"id": st.pk, "vendor": st.vendor.name, "vendor_code": st.vendor.code, "date": st.date, "status": st.status,
            "note": st.note, "countable": services.is_countable(st), "my_records": mine["n"] or 0, "my_quantity": mine["q"] or 0}


class PdaStocktakesView(APIView):
    """Stocktakes this counter is assigned to: open ones from their date on, plus the next days' (not countable yet)."""

    permission_classes = [require(PERFORM)]

    def get(self, request):
        _device(request)
        horizon = timezone.localdate() + timedelta(days=UPCOMING_DAYS)
        qs = (Stocktake.objects.filter(counters=request.user, status=StocktakeStatus.OPEN, date__lte=horizon)
              .select_related("vendor").order_by("date", "vendor__name"))
        return Response([_pda_brief(s, request.user) for s in qs])


class PdaStocktakeRecordsView(APIView):
    permission_classes = [require(PERFORM)]

    def get(self, request, pk):
        """My records (e.g. after reinstalling the app)."""
        st = _my_stocktake(request, pk)
        qs = st.counts.filter(user=request.user, deleted=False).order_by("counted_at")
        return Response({"stocktake": _pda_brief(st, request.user), "records": [{
            "id": str(c.id), "barcode": c.barcode, "quantity": c.quantity, "price": c.price,
            "counted_at": c.counted_at, "updated_at": c.client_updated_at,
        } for c in qs]})

    def post(self, request, pk):
        st = _my_stocktake(request, pk)
        records = request.data.get("records")
        if not isinstance(records, list):
            raise DomainError("invalid_request", "records must be a list")
        out = services.upsert_counts(st, request.user, records, device=_device(request), sent_at=request.data.get("sent_at"))
        st.refresh_from_db()
        return Response({**out, "stocktake": _pda_brief(st, request.user)})
