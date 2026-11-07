import io
import uuid
from datetime import timedelta

import openpyxl
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.testing import make_user

from .models import StockCount, Stocktake, Vendor

B1, B2 = "6260108396830", "012345678905"  # EAN-13; UPC-A (scans as 12 digits, same as 0012345678905)


def rec(barcode, qty, price=None, *, rid=None, at=None, updated=None, deleted=False, title="", typed=False):
    at = at or timezone.now() - timedelta(minutes=5)
    return {"id": rid or str(uuid.uuid4()), "barcode": barcode, "quantity": qty, "price": price, "title": title,
            "title_typed": typed, "counted_at": at.isoformat(), "updated_at": (updated or at).isoformat(), "deleted": deleted}


class StocktakeFlow(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sup = make_user("sup", "supervisor")
        cls.c1, cls.c2 = make_user("s1", "stocktaker"), make_user("s2", "stocktaker")
        cls.checker = make_user("chk", "checker")
        cls.vendor = Vendor.objects.create(name="Vendor A")

    def setUp(self):
        self.client.force_authenticate(self.sup)
        r = self.client.post("/api/stocktakes/", {"vendor_id": self.vendor.pk, "date": timezone.localdate().isoformat(),
                                                  "counter_ids": [self.c1.pk, self.c2.pk]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.st = Stocktake.objects.get(pk=r.data["id"])

    def push(self, user, records, st=None):
        self.client.force_authenticate(user)
        return self.client.post(f"/api/pda/stocktakes/{(st or self.st).pk}/records/",
                                {"sent_at": timezone.now().isoformat(), "records": records}, format="json")

    def test_counters_see_their_stocktakes_only(self):
        tomorrow = Stocktake.objects.create(vendor=self.vendor, date=timezone.localdate() + timedelta(days=1))
        tomorrow.counters.add(self.c1)
        self.client.force_authenticate(self.c1)
        rows = {r["id"]: r for r in self.client.get("/api/pda/stocktakes/").data}
        self.assertTrue(rows[self.st.pk]["countable"])
        self.assertFalse(rows[tomorrow.pk]["countable"])  # visible, but counting starts tomorrow
        self.assertEqual(self.push(self.c1, [rec(B1, 1)], st=tomorrow).data["code"], "stocktake_not_started")
        self.client.force_authenticate(self.checker)
        self.assertEqual(self.client.get("/api/pda/stocktakes/").status_code, 403)

    def test_same_barcode_many_times_is_summed(self):
        tea = "Tea 500g"
        self.push(self.c1, [rec(B1, 10, 25000, title=tea), rec(B1, 4, title=tea), rec(B2, 7, "1200.50"), rec(B2, 0)])
        self.push(self.c2, [rec(" " + B1, 6, 26000, title=tea), rec("0" + B2, 3)])  # same UPC read with a leading zero
        self.client.force_authenticate(self.sup)
        tot = {r["code"]: r for r in self.client.get(f"/api/stocktakes/{self.st.pk}/totals/").data}
        t1 = tot["06260108396830"]
        self.assertEqual((t1["quantity"], t1["records"], t1["counters"], t1["title"]), (20, 3, 2, "Tea 500g"))
        self.assertEqual(t1["price"], 26000)  # last entered price
        self.assertTrue(t1["price_conflict"])
        t2 = tot["00012345678905"]
        self.assertEqual((t2["quantity"], t2["barcode"]), (10, B2))  # exported as most often scanned, no added zeros

    def test_wms_export_format(self):
        self.push(self.c1, [rec(B1, 10, 25000), rec(B2, 7), rec(B1, 5)])
        self.client.force_authenticate(self.sup)
        r = self.client.get(f"/api/stocktakes/{self.st.pk}/export/?kind=wms")
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(rows[0], ("barcode", "title", "count", "price"))
        self.assertEqual(sorted(rows[1:]), [(B2, None, 7, None), (B1, None, 15, 25000)])
        self.assertIsInstance(rows[1][0], str)  # text, so leading zeros survive
        detail = self.client.get(f"/api/stocktakes/{self.st.pk}/export/?kind=detail&lang=fa")
        wb = openpyxl.load_workbook(io.BytesIO(detail.content))
        self.assertEqual(wb.sheetnames, ["Totals", "Records"])
        self.assertEqual(wb["Records"].max_row, 4)

    def test_resend_edit_delete(self):
        rid = str(uuid.uuid4())
        t0 = timezone.now() - timedelta(minutes=10)
        first = rec(B1, 5, rid=rid, at=t0)
        self.assertEqual(self.push(self.c1, [first, first]).data["accepted"], [rid, rid])  # re-sent: no duplicate
        self.assertEqual(StockCount.objects.count(), 1)
        self.push(self.c1, [rec(B1, 8, rid=rid, at=t0, updated=t0 + timedelta(minutes=2))])
        self.push(self.c1, [first])  # an older version arriving late changes nothing
        self.assertEqual(StockCount.objects.get().quantity, 8)
        self.push(self.c1, [rec(B1, 8, rid=rid, at=t0, updated=t0 + timedelta(minutes=3), deleted=True)])
        self.client.force_authenticate(self.sup)
        self.assertEqual(self.client.get(f"/api/stocktakes/{self.st.pk}/totals/").data, [])

    def test_validation_and_ownership(self):
        rid = str(uuid.uuid4())
        self.push(self.c1, [rec(B1, 5, rid=rid)])
        out = self.push(self.c2, [rec(B1, 9, rid=rid), rec("", 1), rec(B1, -1), rec(B1, 2, price="abc"), rec(B1, 0)]).data
        self.assertEqual([x["error"] for x in out["rejected"]], ["not_yours", "invalid_barcode", "invalid_quantity", "invalid_price"])
        self.assertEqual(len(out["accepted"]), 1)  # a count of 0 is allowed
        self.assertEqual(StockCount.objects.get(pk=rid).quantity, 5)

    def test_close_blocks_counting_and_reopen(self):
        self.client.force_authenticate(self.sup)
        self.client.post(f"/api/stocktakes/{self.st.pk}/close/")
        self.assertEqual(self.push(self.c1, [rec(B1, 1)]).status_code, 409)
        self.client.force_authenticate(self.c1)
        self.assertEqual(self.client.get("/api/pda/stocktakes/").data, [])  # closed: no longer on the PDA
        self.client.force_authenticate(self.sup)
        self.client.post(f"/api/stocktakes/{self.st.pk}/reopen/")
        self.assertEqual(self.push(self.c1, [rec(B1, 1)]).status_code, 200)

    def test_not_a_counter(self):
        other = make_user("s3", "stocktaker")
        self.assertEqual(self.push(other, [rec(B1, 1)]).data["code"], "not_a_counter")

    def test_only_stocktakers_can_be_assigned(self):
        self.client.force_authenticate(self.sup)
        r = self.client.patch(f"/api/stocktakes/{self.st.pk}/", {"counter_ids": [self.checker.pk]}, format="json")
        self.assertEqual(r.data["code"], "invalid_counter")
        names = [u["username"] for u in self.client.get("/api/stocktakers/").data]
        self.assertEqual(names, ["s1", "s2"])

    def test_summary_by_counter(self):
        self.push(self.c1, [rec(B1, 10), rec(B2, 2)])
        self.client.force_authenticate(self.sup)
        d = self.client.get(f"/api/stocktakes/{self.st.pk}/").data
        by = {r["username"]: r for r in d["by_counter"]}
        self.assertEqual((by["s1"]["records"], by["s1"]["quantity"], by["s2"]["records"]), (2, 12, 0))
        self.assertEqual((d["totals"]["barcodes"], d["totals"]["quantity"]), (2, 12))

    def test_permissions(self):
        self.client.force_authenticate(self.c1)
        self.assertEqual(self.client.get("/api/stocktakes/").status_code, 403)
        self.client.force_authenticate(self.c1)
        self.assertEqual(self.client.get("/api/pda/barcodes/").status_code, 200)  # stocktakers get the barcode cache too
