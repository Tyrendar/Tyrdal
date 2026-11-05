import io
from datetime import datetime

import jdatetime
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import require
from apps.orders.models import OrderStatus

from . import services
from .services import TZ

# Column definitions for Excel: (key, Persian header, English header, kind).
# kind: int | num | text | dur (seconds) | dt (datetime) | status | ltr
C = {
    "checkers": [
        ("name", "کنترل‌گر", "Checker", "text"), ("orders_checked", "سفارش کنترل‌شده", "Orders checked", "int"),
        ("orders_with_discrepancies", "سفارش دارای مغایرت", "Orders with discrepancies", "int"),
        ("skus_checked", "قلم کنترل‌شده", "SKUs checked", "int"), ("boxes_checked", "کارتن کنترل‌شده", "Boxes checked", "int"),
        ("boxes_scanned", "کارتن اسکن‌شده", "Boxes scanned", "int"), ("active_seconds", "زمان فعال", "Active time", "dur"),
        ("boxes_per_hour", "کارتن در ساعت", "Boxes per hour", "num"),
        ("avg_elapsed_seconds", "میانگین زمان هر سفارش", "Avg time per order", "dur"),
        ("avg_active_seconds", "میانگین زمان فعال هر سفارش", "Avg active time per order", "dur"),
        ("avg_seconds_per_sku", "ثانیه برای هر قلم", "Seconds per SKU", "num"),
        ("shortage_lines", "قلم کسری", "Shortage lines", "int"), ("shortage_boxes", "کارتن کسری", "Shortage boxes", "int"),
        ("extra_boxes", "کارتن اضافه", "Extra boxes", "int"), ("not_in_order_boxes", "کارتن خارج از سفارش", "Not-in-order boxes", "int"),
        ("double_reads", "خوانش تکراری", "Double reads", "int"), ("unknown_scans", "بارکد ناشناس", "Unknown scans", "int"),
        ("mistakes", "اسکن اشتباه", "Mistaken scans", "int"), ("corrections", "اصلاح تعداد", "Corrections", "int"),
    ],
    "pickers": [
        ("picker", "جمع‌آور", "Picker", "text"), ("orders", "سفارش", "Orders", "int"), ("skus", "قلم", "SKUs", "int"),
        ("boxes_ordered", "کارتن سفارش", "Boxes ordered", "int"),
        ("short_picking_lines", "کسری (خطای جمع‌آوری) - قلم", "Short, picking – lines", "int"),
        ("short_picking_boxes", "کسری (خطای جمع‌آوری) - کارتن", "Short, picking – boxes", "int"),
        ("short_stock_lines", "کسری (موجودی) - قلم", "Short, stock – lines", "int"),
        ("short_stock_boxes", "کسری (موجودی) - کارتن", "Short, stock – boxes", "int"),
        ("extra_boxes", "کارتن اضافه", "Extra boxes", "int"), ("not_in_order_boxes", "کارتن خارج از سفارش", "Not-in-order boxes", "int"),
        ("error_boxes", "کارتن خطا", "Error boxes", "int"), ("error_rate_pct", "درصد خطا", "Error rate %", "num"),
    ],
    "reasons": [
        ("type", "نوع", "Type", "text"), ("reason", "دلیل", "Reason", "text"), ("category", "دسته", "Category", "text"),
        ("lines", "قلم", "Lines", "int"), ("boxes", "کارتن", "Boxes", "int"), ("units", "عدد", "Units", "int"),
    ],
    "operations": [
        ("reference_id", "شماره سفارش", "Order ref", "ltr"), ("customer", "مشتری", "Customer", "text"),
        ("picker", "جمع‌آور", "Picker", "text"), ("status", "وضعیت", "Status", "status"), ("checker", "کنترل‌گر", "Checker", "text"),
        ("imported_at", "بارگذاری", "Imported", "dt"), ("assigned_at", "تخصیص", "Assigned", "dt"),
        ("started_at", "شروع کنترل", "Check started", "dt"), ("completed_at", "پایان کنترل", "Check completed", "dt"),
        ("wait_seconds", "انتظار تا شروع", "Wait before start", "dur"), ("elapsed_seconds", "مدت کل", "Elapsed", "dur"),
        ("active_seconds", "زمان فعال", "Active time", "dur"), ("skus", "قلم", "SKUs", "int"), ("skus_done", "قلم انجام‌شده", "SKUs done", "int"),
        ("boxes_ordered", "کارتن سفارش", "Boxes ordered", "int"), ("boxes_scanned", "کارتن اسکن", "Boxes scanned", "int"),
        ("discrepancies", "مغایرت", "Discrepancies", "int"), ("open_discrepancies", "مغایرت باز", "Open discrepancies", "int"),
    ],
}
TITLES = {"checkers": ("عملکرد کنترل‌گرها", "Checker performance"), "pickers": ("گزارش جمع‌آورها", "Picker report"),
          "reasons": ("مغایرت به تفکیک دلیل", "Discrepancies by reason"), "operations": ("پایش عملیات", "Operations"),
          "overview": ("عملکرد کلی", "Overall performance")}
STATUS = {"fa": {"pending_assignment": "در انتظار تخصیص", "assigned": "تخصیص‌یافته", "in_progress": "در حال کنترل", "completed": "تکمیل‌شده", "cancelled": "لغوشده"},
          "en": {s.value: s.label for s in OrderStatus}}
TYPES = {"fa": {"short": "کسری", "extra": "اضافه", "not_in_order": "خارج از سفارش"}, "en": {"short": "Shortage", "extra": "Extra", "not_in_order": "Not in order"}}
CATEGORIES = {"fa": {"stock": "موجودی", "picking": "جمع‌آوری", "scanning": "اسکن", "other": "سایر"},
              "en": {"stock": "Stock", "picking": "Picking", "scanning": "Scanning", "other": "Other"}}
OVERVIEW_ROWS = [
    ("orders_assigned", "سفارش تخصیص‌یافته", "Orders assigned", "int"), ("orders_checked", "سفارش کنترل‌شده", "Orders checked", "int"),
    ("orders_with_discrepancies", "سفارش دارای مغایرت", "Orders with discrepancies", "int"), ("skus_checked", "قلم کنترل‌شده", "SKUs checked", "int"),
    ("boxes_checked", "کارتن کنترل‌شده", "Boxes checked", "int"), ("boxes_scanned", "کارتن اسکن‌شده", "Boxes scanned", "int"),
    ("discrepancies", "مغایرت‌ها", "Discrepancies", "int"), ("shortage_boxes", "کارتن کسری", "Shortage boxes", "int"),
    ("extra_boxes", "کارتن اضافه", "Extra boxes", "int"), ("not_in_order_boxes", "کارتن خارج از سفارش", "Not-in-order boxes", "int"),
    ("avg_elapsed_seconds", "میانگین زمان هر سفارش", "Avg time per order", "dur"),
    ("avg_active_seconds", "میانگین زمان فعال هر سفارش", "Avg active time per order", "dur"),
    ("avg_seconds_per_sku", "ثانیه برای هر قلم", "Seconds per SKU", "num"),
]


def _dur(s):
    if s is None:
        return None
    s = int(s)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _cell(v, kind, lang):
    if v is None:
        return None
    if kind == "dur":
        return _dur(v)
    if kind == "status":
        return STATUS[lang].get(v, v)
    if kind == "dt":
        local = v.astimezone(TZ)
        if lang == "fa":
            return jdatetime.datetime.fromgregorian(datetime=local.replace(tzinfo=None)).strftime("%Y/%m/%d %H:%M")
        return local.replace(tzinfo=None)
    return v


def xlsx(name: str, period: dict, columns, rows, lang: str) -> HttpResponse:
    wb = Workbook()
    ws = wb.active
    ws.title = TITLES[name][1][:31]
    if lang == "fa":
        ws.sheet_view.rightToLeft = True
    title = TITLES[name][0 if lang == "fa" else 1]
    ws.append([f"{title}  ({period['from']} → {period['to']})"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append([c[1] if lang == "fa" else c[2] for c in columns])
    for cell in ws[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0F766E")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r in rows:
        ws.append([_cell(r.get(c[0]), c[3], lang) for c in columns])
    for i, c in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 28 if c[3] in ("text", "dt") else 16
        if c[3] == "dt" and lang != "fa":
            for row in ws.iter_rows(min_row=4, min_col=i, max_col=i):
                row[0].number_format = "yyyy-mm-dd hh:mm"
    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{name}_{period["from"]}_{period["to"]}.xlsx"'
    return resp


class _Report(APIView):
    permission_classes = [require("reports.view")]
    name = ""

    def params(self, request):
        p = request.query_params
        return services.parse_period(p), (int(p["checker"]) if (p.get("checker") or "").isdigit() else None), p.get("lang", "fa")

    def respond(self, request, data, columns=None, rows=None):
        if request.query_params.get("export") == "xlsx":
            lang = request.query_params.get("lang", "fa")
            return xlsx(self.name, data["period"], columns or C[self.name], rows if rows is not None else data["rows"], "fa" if lang == "fa" else "en")
        return Response(data)


class OverviewReport(_Report):
    name = "overview"

    def get(self, request):
        period, checker, lang = self.params(request)
        data = services.overview(period, checker)
        rows = [{"metric": (r[1] if lang == "fa" else r[2]), "value": _cell(data[r[0]], r[3], lang)} for r in OVERVIEW_ROWS]
        cols = [("metric", "شاخص", "Metric", "text"), ("value", "مقدار", "Value", "text")]
        return self.respond(request, data, cols, rows)


class CheckersReport(_Report):
    name = "checkers"

    def get(self, request):
        period, checker, _ = self.params(request)
        return self.respond(request, services.checkers(period, checker))


class PickersReport(_Report):
    name = "pickers"

    def get(self, request):
        period, _, _ = self.params(request)
        return self.respond(request, services.pickers(period))


class ReasonsReport(_Report):
    name = "reasons"

    def get(self, request):
        period, checker, lang = self.params(request)
        picker = request.query_params.get("picker")
        data = services.reasons(period, checker, picker if picker is not None and picker != "" else None)
        lang = "fa" if lang == "fa" else "en"
        rows = [{**r, "type": TYPES[lang].get(r["type"], r["type"]), "category": CATEGORIES[lang].get(r["category"], r["category"]),
                 "reason": (r["name_fa"] if lang == "fa" else r["name_en"]) or "—"} for r in data["rows"]]
        return self.respond(request, data, rows=rows)


class OperationsReport(_Report):
    name = "operations"

    def get(self, request):
        period, checker, _ = self.params(request)
        status = [s for s in (request.query_params.get("status") or "").split(",") if s]
        return self.respond(request, services.operations(period, status or None, checker, request.query_params.get("q", "")))
