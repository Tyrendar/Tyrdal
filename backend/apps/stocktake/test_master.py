import io
import uuid
from datetime import timedelta

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.testing import make_user

from .models import MasterItem, Stocktake, Vendor

CSV = (
    "﻿بارکد,شرح کالا,قیمت\r\n"
    "6260108396830,چای ۵۰۰ گرمی,250000\r\n"
    "23028982,آرد ذرت 450 گرم,370000\r\n"
    "23028982,آرد ذرت 400 گرم,1450000\r\n"
    "23028982,آرد ذرت 400 گرم,1450000\r\n"  # exact duplicate row
    ",بدون بارکد,1000\r\n"  # error: no barcode
    "1112223334445,,1000\r\n"  # error: no title
)


def upload(client, text=CSV, mode="merge", dry_run=False, name="master.csv"):
    f = SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")
    return client.post("/api/stocktake-master/import/", {"file": f, "mode": mode, "dry_run": str(dry_run).lower()}, format="multipart")


def rec(barcode, qty, title="", typed=False):
    at = timezone.now() - timedelta(minutes=1)
    return {"id": str(uuid.uuid4()), "barcode": barcode, "quantity": qty, "title": title, "title_typed": typed,
            "counted_at": at.isoformat(), "updated_at": at.isoformat()}


class MasterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sup = make_user("sup", "supervisor")
        cls.counter = make_user("s1", "stocktaker")
        cls.st = Stocktake.objects.create(vendor=Vendor.objects.create(name="V"), date=timezone.localdate())
        cls.st.counters.add(cls.counter)

    def setUp(self):
        self.client.force_authenticate(self.sup)

    def test_import_preview_then_merge(self):
        preview = upload(self.client, dry_run=True).data
        self.assertEqual((preview["new"], preview["errors"], preview["duplicate_rows"]), (3, 2, 1))
        self.assertEqual(preview["barcodes_with_several_titles"], 1)
        self.assertEqual(MasterItem.objects.count(), 0)  # dry run changes nothing
        done = upload(self.client).data
        self.assertEqual(done["new"], 3)
        self.assertEqual(MasterItem.objects.filter(code="23028982").count(), 2)  # two titles kept
        again = upload(self.client, CSV.replace("370000", "380000")).data
        self.assertEqual((again["new"], again["updated"], again["unchanged"]), (0, 1, 2))

    def test_replace_keeps_manual_and_counter_items(self):
        upload(self.client)
        self.client.post("/api/stocktake-master/", {"barcode": "9990001112223", "title": "Manual item"}, format="json")
        self.client.force_authenticate(self.counter)
        self.client.post(f"/api/pda/stocktakes/{self.st.pk}/records/",
                         {"records": [rec("7770001112229", 3, "Typed by counter", typed=True)]}, format="json")
        self.client.force_authenticate(self.sup)
        res = upload(self.client, "barcode,title\r\n6260108396830,چای ۵۰۰ گرمی\r\n", mode="replace").data
        self.assertEqual(res["removed"], 2)  # the two flour items from the previous import
        live = set(MasterItem.objects.filter(deleted=False).values_list("title", "source"))
        self.assertEqual(live, {("چای ۵۰۰ گرمی", "import"), ("Manual item", "manual"), ("Typed by counter", "counter")})

    def test_counter_title_added_once_and_respects_panel_delete(self):
        self.client.force_authenticate(self.counter)
        url = f"/api/pda/stocktakes/{self.st.pk}/records/"
        self.client.post(url, {"records": [rec("7770001112229", 3, "New thing", typed=True), rec("7770001112229", 2, "New thing", typed=True)]}, format="json")
        self.assertEqual(MasterItem.objects.filter(code="07770001112229", source="counter").count(), 1)
        item = MasterItem.objects.get(code="07770001112229")
        self.client.force_authenticate(self.sup)
        self.client.delete(f"/api/stocktake-master/{item.pk}/")
        self.client.force_authenticate(self.counter)
        self.client.post(url, {"records": [rec("7770001112229", 1, "New thing", typed=True)]}, format="json")
        self.assertFalse(MasterItem.objects.filter(code="07770001112229", deleted=False).exists())  # deleted stays deleted
        # A title chosen from the master is not "typed": nothing is added.
        self.client.post(url, {"records": [rec("8880001112220", 1, "Chosen")]}, format="json")
        self.assertFalse(MasterItem.objects.filter(code="08880001112220").exists())

    def test_totals_and_export_by_barcode_and_title(self):
        self.client.force_authenticate(self.counter)
        self.client.post(f"/api/pda/stocktakes/{self.st.pk}/records/", {"records": [
            rec("23028982", 5, "آرد ذرت 450 گرم"), rec("23028982", 2, "آرد ذرت 400 گرم"), rec("23028982", 1, "آرد ذرت 450 گرم"),
        ]}, format="json")
        self.client.force_authenticate(self.sup)
        r = self.client.get(f"/api/stocktakes/{self.st.pk}/export/?kind=wms")
        rows = list(openpyxl.load_workbook(io.BytesIO(r.content)).active.iter_rows(values_only=True))
        self.assertEqual(rows[0], ("barcode", "title", "count", "price"))
        self.assertEqual(sorted(rows[1:]), [("23028982", "آرد ذرت 400 گرم", 2, None), ("23028982", "آرد ذرت 450 گرم", 6, None)])

    def test_pda_feed_with_deletions(self):
        upload(self.client)
        self.client.force_authenticate(self.counter)
        first = self.client.get("/api/pda/stocktake-master/").data
        self.assertEqual(len(first["items"]), 3)
        self.assertFalse(first["has_more"])
        since = first["server_time"].isoformat()
        self.client.force_authenticate(self.sup)
        item = MasterItem.objects.get(title="آرد ذرت 450 گرم")
        self.client.delete(f"/api/stocktake-master/{item.pk}/")
        self.client.patch(f"/api/stocktake-master/{MasterItem.objects.get(title='چای ۵۰۰ گرمی').pk}/", {"title": "چای ۴۵۰ گرمی"}, format="json")
        self.client.force_authenticate(self.counter)
        delta = self.client.get("/api/pda/stocktake-master/", {"since": since}).data["items"]
        self.assertEqual(sorted((d["title"], d["deleted"]) for d in delta), [("آرد ذرت 450 گرم", True), ("چای ۴۵۰ گرمی", False)])

    def test_panel_crud_and_duplicates(self):
        r = self.client.post("/api/stocktake-master/", {"barcode": "6260108396830", "title": "Tea"}, format="json")
        self.assertEqual(r.status_code, 201)
        dup = self.client.post("/api/stocktake-master/", {"barcode": " 6260108396830", "title": "Tea"}, format="json")
        self.assertEqual(dup.data["code"], "duplicate_item")
        self.assertEqual(self.client.post("/api/stocktake-master/", {"barcode": "6260108396830", "title": "Tea 2"}, format="json").status_code, 201)
        found = self.client.get("/api/stocktake-master/", {"q": "6260108396830"}).data["results"]
        self.assertEqual(len(found), 2)
        self.assertEqual(self.client.get("/api/stocktake-master/stats/").data["multi_title_barcodes"], 1)

    def test_xlsx_and_missing_columns(self):
        wb = openpyxl.Workbook()
        wb.active.append(["Barcode", "Title"])
        wb.active.append([6260108396830, "Tea"])  # numeric cell
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile("m.xlsx", buf.getvalue())
        r = self.client.post("/api/stocktake-master/import/", {"file": f, "dry_run": "false"}, format="multipart")
        self.assertEqual(r.data["new"], 1)
        self.assertEqual(MasterItem.objects.get().barcode, "6260108396830")
        bad = upload(self.client, "foo,bar\r\n1,2\r\n")
        self.assertEqual(bad.data["code"], "missing_columns")

    def test_permissions(self):
        self.client.force_authenticate(self.counter)
        self.assertEqual(self.client.get("/api/stocktake-master/").status_code, 403)
        checker = make_user("chk", "checker")
        self.client.force_authenticate(checker)
        self.assertEqual(self.client.get("/api/pda/stocktake-master/").status_code, 403)
