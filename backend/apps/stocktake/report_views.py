from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import require
from apps.reports.services import parse_period
from apps.reports.views import xlsx

from . import reports

ST_STATUS = {"fa": {"open": "باز", "closed": "بسته"}, "en": {"open": "Open", "closed": "Closed"}}

# (key, Persian header, English header, kind) — kinds as in apps.reports.views._cell
COLUMNS = {
    "counters": [
        ("name", "انبارگردان", "Counter", "text"), ("stocktakes", "انبارگردانی", "Stocktakes", "int"),
        ("records", "ثبت", "Records", "int"), ("units", "تعداد شمرده‌شده", "Units counted", "int"),
        ("barcodes", "بارکد", "Barcodes", "int"), ("active_seconds", "زمان فعال", "Active time", "dur"),
        ("records_per_hour", "ثبت در ساعت", "Records per hour", "num"), ("units_per_hour", "عدد در ساعت", "Units per hour", "num"),
        ("typed_titles", "نام تایپ‌شده", "Typed titles", "int"), ("edited", "ویرایش‌شده", "Edited", "int"),
        ("deleted", "حذف‌شده", "Deleted", "int"), ("first_at", "اولین ثبت", "First record", "dt"), ("last_at", "آخرین ثبت", "Last record", "dt"),
    ],
    "vendors": [
        ("vendor", "وندور", "Vendor", "text"), ("stocktakes", "انبارگردانی", "Stocktakes", "int"),
        ("records", "ثبت", "Records", "int"), ("units", "تعداد شمرده‌شده", "Units counted", "int"), ("barcodes", "بارکد", "Barcodes", "int"),
        ("counters", "انبارگردان", "Counters", "int"), ("with_price", "ثبت با قیمت", "Records with price", "int"),
        ("value", "ارزش (تعداد × قیمت)", "Value (count × price)", "num"), ("last_at", "آخرین ثبت", "Last record", "dt"),
    ],
    "stocktakes": [
        ("vendor", "وندور", "Vendor", "text"), ("date", "تاریخ", "Date", "date"), ("status", "وضعیت", "Status", "text"),
        ("counters", "انبارگردان‌ها", "Counters", "text"), ("records", "ثبت", "Records", "int"), ("units", "تعداد", "Units", "int"),
        ("barcodes", "بارکد", "Barcodes", "int"), ("typed_titles", "نام تایپ‌شده", "Typed titles", "int"),
        ("first_at", "شروع", "First record", "dt"), ("last_at", "پایان", "Last record", "dt"),
        ("elapsed_seconds", "مدت", "Elapsed", "dur"), ("closed_at", "بسته شد", "Closed", "dt"),
    ],
    "new-titles": [
        ("barcode", "بارکد", "Barcode", "text"), ("title", "نام تایپ‌شده", "Typed title", "text"),
        ("other_titles", "نام‌های دیگر در فهرست", "Other titles in the list", "text"), ("counter", "انبارگردان", "Counter", "text"),
        ("created_at", "زمان", "Time", "dt"), ("deleted", "حذف‌شده از فهرست", "Deleted from list", "text"),
    ],
}
TITLES = {
    "overview": ("انبارگردانی - عملکرد کلی", "Stocktaking overview"), "counters": ("عملکرد انبارگردان‌ها", "Counter performance"),
    "vendors": ("انبارگردانی به تفکیک وندور", "Stocktaking by vendor"), "stocktakes": ("انبارگردانی‌ها", "Stocktakes"),
    "new-titles": ("نام‌های تایپ‌شده توسط انبارگردان", "Titles typed by counters"),
}
OVERVIEW_ROWS = [
    ("stocktakes_planned", "انبارگردانی در بازه", "Stocktakes in period", "int"), ("stocktakes_closed", "بسته‌شده", "Closed", "int"),
    ("stocktakes_counted", "انبارگردانی دارای ثبت", "Stocktakes with records", "int"), ("vendors", "وندور", "Vendors", "int"),
    ("counters", "انبارگردان", "Counters", "int"), ("records", "ثبت", "Records", "int"), ("units", "تعداد شمرده‌شده", "Units counted", "int"),
    ("barcodes", "بارکد", "Barcodes", "int"), ("typed_titles", "نام تایپ‌شده", "Typed titles", "int"),
    ("without_title", "بدون نام", "Without title", "int"), ("with_price", "ثبت با قیمت", "Records with price", "int"),
    ("value", "ارزش (تعداد × قیمت)", "Value (count × price)", "num"), ("active_seconds", "زمان فعال", "Active time", "dur"),
    ("records_per_hour", "ثبت در ساعت", "Records per hour", "num"),
]


class _StockReport(APIView):
    permission_classes = [require("stocktake.manage")]
    name = ""

    def params(self, request):
        q = request.query_params
        num = lambda k: int(q[k]) if (q.get(k) or "").isdigit() else None  # noqa: E731
        return parse_period(q), num("vendor"), num("counter"), ("en" if q.get("lang") == "en" else "fa")

    def respond(self, request, data, lang, rows=None, columns=None):
        if request.query_params.get("export") != "xlsx":
            return Response(data)
        rows = data["rows"] if rows is None else rows
        return xlsx(self.name, data["period"], columns or COLUMNS[self.name], rows, lang, titles=TITLES[self.name])


class OverviewView(_StockReport):
    name = "overview"

    def get(self, request):
        p, vendor, counter, lang = self.params(request)
        data = reports.overview(p, vendor, counter)
        from apps.reports.views import _cell

        rows = [{"metric": r[1] if lang == "fa" else r[2], "value": _cell(data[r[0]], r[3], lang)} for r in OVERVIEW_ROWS]
        return self.respond(request, data, lang, rows, [("metric", "شاخص", "Metric", "text"), ("value", "مقدار", "Value", "text")])


class CountersView(_StockReport):
    name = "counters"

    def get(self, request):
        p, vendor, counter, lang = self.params(request)
        return self.respond(request, reports.counters(p, vendor, counter), lang)


class VendorsView(_StockReport):
    name = "vendors"

    def get(self, request):
        p, vendor, counter, lang = self.params(request)
        return self.respond(request, reports.vendors(p, vendor, counter), lang)


class StocktakesView(_StockReport):
    name = "stocktakes"

    def get(self, request):
        p, vendor, counter, lang = self.params(request)
        data = reports.stocktakes(p, vendor, counter, request.query_params.get("status"))
        rows = [{**r, "status": ST_STATUS[lang].get(r["status"], r["status"])} for r in data["rows"]]
        return self.respond(request, data, lang, rows)


class NewTitlesView(_StockReport):
    name = "new-titles"

    def get(self, request):
        p, _vendor, counter, lang = self.params(request)
        data = reports.new_titles(p, counter)
        yes = "بله" if lang == "fa" else "Yes"
        rows = [{**r, "deleted": yes if r["deleted"] else None} for r in data["rows"]]
        return self.respond(request, data, lang, rows)
