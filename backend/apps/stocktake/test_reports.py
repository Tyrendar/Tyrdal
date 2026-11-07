import io
import uuid
from datetime import timedelta

import openpyxl
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.testing import make_user

from .models import MasterItem, Stocktake, Vendor


def rec(barcode, qty, at, *, price=None, title="", typed=False, updated=None, deleted=False):
    return {"id": str(uuid.uuid4()), "barcode": barcode, "quantity": qty, "price": price, "title": title, "title_typed": typed,
            "counted_at": at.isoformat(), "updated_at": (updated or at).isoformat(), "deleted": deleted}


class StocktakeReports(APITestCase):
    """Two vendors, two counters, known numbers."""

    @classmethod
    def setUpTestData(cls):
        cls.sup = make_user("sup", "supervisor")
        cls.c1, cls.c2 = make_user("s1", "stocktaker"), make_user("s2", "stocktaker")
        today = timezone.localdate()
        cls.va, cls.vb = Vendor.objects.create(name="Vendor A"), Vendor.objects.create(name="Vendor B")
        cls.sa = Stocktake.objects.create(vendor=cls.va, date=today)
        cls.sa.counters.add(cls.c1, cls.c2)
        cls.sb = Stocktake.objects.create(vendor=cls.vb, date=today)
        cls.sb.counters.add(cls.c2)

    def setUp(self):
        t0 = timezone.now() - timedelta(minutes=40)
        push = lambda user, st, recs: (self.client.force_authenticate(user),  # noqa: E731
                                       self.client.post(f"/api/pda/stocktakes/{st.pk}/records/", {"records": recs}, format="json"))
        # c1 on A: 3 records 30 s apart, a 20-minute break, 1 more (30 s, 30 s, break ignored) -> active 60 s.
        push(self.c1, self.sa, [
            rec("1001", 10, t0, price="1000"), rec("1002", 5, t0 + timedelta(seconds=30), title="Typed", typed=True),
            rec("1001", 2, t0 + timedelta(seconds=60), updated=t0 + timedelta(minutes=5)),  # edited later
            rec("1003", 1, t0 + timedelta(minutes=21)),
        ])
        # c2: 1 record on A, 2 on B (one deleted), 10 s apart -> active 20 s.
        push(self.c2, self.sa, [rec("1001", 4, t0 + timedelta(seconds=10))])
        push(self.c2, self.sb, [rec("2001", 7, t0 + timedelta(seconds=20), price="200"),
                                rec("2002", 9, t0 + timedelta(seconds=30), deleted=True)])
        self.client.force_authenticate(self.sup)
        today = timezone.localdate()
        self.q = {"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat()}

    def get(self, name, **extra):
        r = self.client.get(f"/api/stocktake-reports/{name}/", {**self.q, **extra})
        self.assertEqual(r.status_code, 200, getattr(r, "data", r.content))
        return r

    def test_overview(self):
        d = self.get("overview").data
        self.assertEqual((d["records"], d["units"], d["barcodes"], d["counters"], d["vendors"]), (6, 29, 4, 2, 2))
        self.assertEqual((d["typed_titles"], d["with_price"], d["stocktakes_planned"]), (1, 2, 2))
        self.assertEqual(d["value"], 10 * 1000 + 7 * 200)
        self.assertEqual(d["now"]["new_titles_to_review"], 1)
        only_b = self.get("overview", vendor=self.vb.pk).data
        self.assertEqual((only_b["records"], only_b["units"]), (1, 7))

    def test_counters(self):
        rows = {r["username"]: r for r in self.get("counters").data["rows"]}
        c1, c2 = rows["s1"], rows["s2"]
        self.assertEqual((c1["records"], c1["units"], c1["barcodes"], c1["stocktakes"]), (4, 18, 3, 1))
        self.assertEqual((c1["active_seconds"], c1["edited"], c1["typed_titles"]), (60, 1, 1))
        self.assertEqual(c1["records_per_hour"], 240.0)
        self.assertEqual((c2["records"], c2["deleted"], c2["stocktakes"], c2["active_seconds"]), (2, 1, 2, 20))

    def test_vendors_and_stocktakes(self):
        v = {r["vendor"]: r for r in self.get("vendors").data["rows"]}
        self.assertEqual((v["Vendor A"]["units"], v["Vendor A"]["counters"], v["Vendor B"]["units"]), (22, 2, 7))
        s = {r["vendor"]: r for r in self.get("stocktakes").data["rows"]}
        self.assertEqual((s["Vendor A"]["records"], s["Vendor A"]["barcodes"], s["Vendor A"]["counters_n"]), (5, 3, 2))
        self.assertEqual(s["Vendor A"]["elapsed_seconds"], 21 * 60)

    def test_new_titles(self):
        MasterItem.objects.create(code="1002", barcode="1002", title="From file", source="import")
        rows = self.get("new-titles").data["rows"]
        self.assertEqual([(r["title"], r["other_titles"], r["counter"]) for r in rows], [("Typed", "From file", "S1")])

    def test_excel_exports(self):
        for name in ("overview", "counters", "vendors", "stocktakes", "new-titles"):
            r = self.get(name, export="xlsx", lang="fa")
            self.assertIn("spreadsheetml", r["Content-Type"], name)
            ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
            self.assertTrue(ws.sheet_view.rightToLeft, name)
        ws = openpyxl.load_workbook(io.BytesIO(self.get("stocktakes", export="xlsx", lang="fa").content)).active
        self.assertEqual(ws.cell(4, 3).value, "باز")

    def test_permission(self):
        self.client.force_authenticate(self.c1)
        self.assertEqual(self.client.get("/api/stocktake-reports/overview/").status_code, 403)
