from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.checking import engine
from apps.checking.models import DiscrepancyReason
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.testing import Clock, ev, import_orders, line, make_user

B1, B2, B3, UNKNOWN = "6260108396830", "6260055843500", "6260113899210", "1234567890128"


class ReportScenario(APITestCase):
    """Two orders, two checkers, two pickers, with known numbers."""

    @classmethod
    def setUpTestData(cls):
        cls.sup = make_user("sup", "supervisor")
        cls.c1, cls.c2 = make_user("c1"), make_user("c2")
        import_orders([
            line("1", "P1", (B1,), pack=1, inc=12, picker="Ali"),
            line("1", "P2", (B2,), pack=3, inc=6, picker="Ali"),
            line("1", "P3", (B3,), pack=2, inc=24, picker="Ali"),
            line("2", "P1", (B1,), pack=1, inc=12, customer="Store B", picker="Reza"),
        ])
        o1, o2 = Order.objects.get(reference_id="1"), Order.objects.get(reference_id="2")
        order_services.assign(o1, cls.c1, by=cls.sup)
        order_services.assign(o2, cls.c2, by=cls.sup)
        # The scenario happened in the past hour (events may not be in the future).
        from apps.orders.models import Assignment

        Assignment.objects.update(assigned_at=timezone.now() - timedelta(hours=1))
        no_stock = DiscrepancyReason.objects.get(code="no_stock").pk

        # c1: 4 boxes 10 s apart, a 20-minute break, then an extra box and a shortage.
        clk = Clock(start=timezone.now() - timedelta(minutes=50))
        run = lambda order, user, *evs: engine.process_events(order.pk, user, list(evs))["results"]  # noqa: E731
        run(o1, cls.c1, ev("scan", clk, 10_000, barcode=B1), ev("scan", clk, 10_000, barcode=B2),
            ev("scan", clk, 10_000, barcode=B2), ev("scan", clk, 10_000, barcode=B2))
        over = run(o1, cls.c1, ev("scan", clk, 20 * 60_000, barcode=B1))[0]
        run(o1, cls.c1, ev("extra_decision", clk, 10_000, ref=over["id"], decision="removed"),
            ev("declare_short", clk, 10_000, line_id=o1.lines.get(product_id="P3").pk, reason_id=no_stock))
        engine.finish(o1.pk, cls.c1)

        # c2: 1 box, one scanner double-read, one unknown barcode.
        clk2 = Clock(start=timezone.now() - timedelta(minutes=10))
        run(o2, cls.c2, ev("scan", clk2, 5_000, barcode=B1), ev("scan", clk2, 100, barcode=B1, duplicate=True),
            ev("scan", clk2, 5_000, barcode=UNKNOWN))
        engine.finish(o2.pk, cls.c2)
        cls.o1, cls.o2 = o1, o2

    def setUp(self):
        self.client.force_authenticate(self.sup)
        today = timezone.localdate()
        self.q = {"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat()}

    def get(self, name, **extra):
        r = self.client.get(f"/api/reports/{name}/", {**self.q, **extra})
        self.assertEqual(r.status_code, 200, getattr(r, "data", r.content))
        return r

    def test_active_time_excludes_breaks(self):
        o1 = Order.objects.get(pk=self.o1.pk)
        # 3 gaps of 10 s, the 20-minute gap ignored, then 2 more 10 s gaps.
        self.assertEqual(o1.active_seconds, 50)

    def test_overview(self):
        d = self.get("overview").data
        self.assertEqual((d["orders_checked"], d["orders_assigned"], d["orders_with_discrepancies"]), (2, 2, 1))
        self.assertEqual((d["skus_checked"], d["boxes_ordered"], d["boxes_checked"], d["boxes_scanned"]), (4, 7, 5, 5))
        self.assertEqual((d["discrepancies"], d["shortage_lines"], d["shortage_boxes"], d["shortage_units"]), (2, 1, 2, 48))
        self.assertEqual((d["extra_boxes"], d["not_in_order_boxes"]), (1, 0))
        self.assertEqual(d["now"]["in_progress"], 0)
        self.assertEqual(sum(x["orders_completed"] for x in d["by_day"]), 2)

    def test_checkers(self):
        rows = {r["username"]: r for r in self.get("checkers").data["rows"]}
        c1, c2 = rows["c1"], rows["c2"]
        self.assertEqual((c1["orders_checked"], c1["skus_checked"], c1["boxes_scanned"]), (1, 3, 4))
        self.assertEqual((c1["shortage_boxes"], c1["extra_boxes"], c1["active_seconds"]), (2, 1, 50))
        self.assertEqual(c1["boxes_per_hour"], 288.0)  # 4 boxes in 50 s
        self.assertEqual((c2["boxes_scanned"], c2["double_reads"], c2["unknown_scans"]), (1, 1, 1))
        only_c2 = self.get("checkers", checker=self.c2.pk).data["rows"]
        self.assertEqual([r["username"] for r in only_c2], ["c2"])

    def test_pickers(self):
        rows = {r["picker"]: r for r in self.get("pickers").data["rows"]}
        ali, reza = rows["Ali"], rows["Reza"]
        # "No stock" is a stock shortage, not a picker error; the removed extra box is.
        self.assertEqual((ali["short_stock_boxes"], ali["short_picking_boxes"], ali["extra_boxes"]), (2, 0, 1))
        self.assertEqual((ali["error_boxes"], ali["error_rate_pct"]), (1, round(100 / 6, 2)))
        self.assertEqual(reza["error_boxes"], 0)

    def test_reasons(self):
        rows = {r["code"]: r for r in self.get("reasons").data["rows"]}
        self.assertEqual((rows["no_stock"]["boxes"], rows["no_stock"]["units"]), (2, 48))
        self.assertEqual(rows["extra_item"]["boxes"], 1)
        self.assertEqual(self.get("reasons", picker="Reza").data["rows"], [])

    def test_operations(self):
        rows = {r["reference_id"]: r for r in self.get("operations").data["rows"]}
        self.assertEqual(rows["1"]["active_seconds"], 50)
        self.assertTrue(rows["1"]["elapsed_seconds"] >= 20 * 60)
        self.assertIsNotNone(rows["1"]["assigned_at"])
        self.assertEqual(rows["1"]["checker"], "C1")

    def test_period_outside_returns_nothing(self):
        d = self.get("overview", **{"from": "2020-01-01", "to": "2020-01-31"}).data
        self.assertEqual((d["orders_checked"], d["boxes_scanned"]), (0, 0))

    def test_excel_export(self):
        import io

        import openpyxl

        for name in ("overview", "checkers", "pickers", "reasons", "operations"):
            r = self.get(name, export="xlsx", lang="fa")
            self.assertIn("spreadsheetml", r["Content-Type"])
            ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
            self.assertTrue(ws.sheet_view.rightToLeft, name)
        ws = openpyxl.load_workbook(io.BytesIO(self.get("checkers", export="xlsx", lang="en").content)).active
        self.assertEqual(ws.cell(3, 1).value, "Checker")

    def test_permission(self):
        self.client.force_authenticate(self.c1)
        self.assertEqual(self.client.get("/api/reports/overview/").status_code, 403)
