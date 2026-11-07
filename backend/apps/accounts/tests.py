"""HTTP-level tests: auth, role permissions, checker isolation and the PDA flow end to end."""
import uuid

from rest_framework.test import APITestCase

from apps.orders.models import Order
from apps.testing import Clock, line, make_user, upload

B1, B2 = "6260108396830", "6260055843500"


class ApiTestBase(APITestCase):
    def setUp(self):
        self.admin = make_user("admin", "admin")
        self.sup = make_user("sup", "supervisor")
        self.c1 = make_user("c1")
        self.c2 = make_user("c2")

    def login(self, username, password="pass1234", **extra):
        r = self.client.post("/api/auth/login/", {"username": username, "password": password, **extra}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        return r.data

    def import_file(self, rows):
        self.login("sup")
        r = self.client.post("/api/imports/", {"kind": "orders", "file": upload(rows, name=f"{uuid.uuid4().hex}.xlsx")}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post(f"/api/imports/{r.data['id']}/commit/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data


class AuthAndPermissionTests(ApiTestBase):
    def test_login_returns_user_and_registers_device(self):
        data = self.login("c1", device_serial="UROVO-123", device_model="Urovo DT50", app_version="1.0")
        self.assertEqual(data["user"]["role"], "checker")
        self.assertEqual(data["user"]["permissions"], ["checking.perform"])
        self.assertIn("device_id", data)

    def test_wrong_password(self):
        r = self.client.post("/api/auth/login/", {"username": "c1", "password": "nope"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_inactive_user_cannot_login(self):
        self.c1.is_active = False
        self.c1.save()
        r = self.client.post("/api/auth/login/", {"username": "c1", "password": "pass1234"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_checker_cannot_use_admin_endpoints(self):
        self.login("c1")
        for url in ("/api/orders/", "/api/users/", "/api/imports/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.post("/api/imports/", {"kind": "orders", "file": upload([line()])}, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_supervisor_cannot_manage_users_but_admin_can(self):
        self.login("sup")
        self.assertEqual(self.client.get("/api/users/").status_code, 403)
        self.login("admin")
        r = self.client.post("/api/users/", {"username": "c3", "password": "1234", "roles": ["checker"], "full_name": "C3"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post(f"/api/users/{r.data['id']}/reset-password/", {"password": "5678"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.login("c3", "5678")

    def test_permissions_are_configurable(self):
        self.login("admin")
        r = self.client.put("/api/role-permissions/", {"role": "supervisor", "permissions": ["orders.view"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.login("sup")
        r = self.client.post("/api/imports/", {"kind": "orders", "file": upload([line()])}, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_reasons_managed_by_supervisor_and_listed_for_pda(self):
        self.login("sup")
        r = self.client.post("/api/reasons/", {"code": "expired", "name_fa": "تاریخ گذشته", "name_en": "Expired",
                                               "applies_to": "short"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.client.patch(f"/api/reasons/{r.data['id']}/", {"is_active": False}, format="json")
        self.login("c1")
        codes = [x["code"] for x in self.client.get("/api/pda/config/").data["reasons"]]
        self.assertIn("no_stock", codes)
        self.assertNotIn("expired", codes)


class ImportApiTests(ApiTestBase):
    def test_upload_preview_commit_and_duplicate_file(self):
        self.login("sup")
        f = upload([line("1", "P1"), line("2", "P1")], name="a.xlsx")
        content = f.read()
        f.seek(0)
        r = self.client.post("/api/imports/", {"kind": "orders", "file": f}, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["preview"]["importable"], 2)
        bid = r.data["id"]
        self.assertEqual(self.client.post(f"/api/imports/{bid}/commit/").status_code, 200)
        self.assertEqual(Order.objects.count(), 2)
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post("/api/imports/", {"kind": "orders", "file": SimpleUploadedFile("b.xlsx", content)}, format="multipart")
        self.assertEqual((r.status_code, r.data["code"]), (409, "duplicate_file"))

    def test_rejects_non_excel(self):
        self.login("sup")
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post("/api/imports/", {"kind": "orders", "file": SimpleUploadedFile("a.csv", b"x")}, format="multipart")
        self.assertEqual(r.data["code"], "unsupported_file_type")


class PdaFlowTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.import_file([line("1", "P1", (B1,), pack=1), line("1", "P2", (B2,), pack=2, inc=6),
                          line("2", "P1", (B1,), customer="Other")])
        self.o1 = Order.objects.get(reference_id="1")
        self.o2 = Order.objects.get(reference_id="2")
        self.client.post(f"/api/orders/{self.o1.pk}/assign/", {"checker_id": self.c1.pk}, format="json")
        self.client.post(f"/api/orders/{self.o2.pk}/assign/", {"checker_id": self.c2.pk}, format="json")
        self.clock = Clock()

    def events(self, order_id, *evs):
        return self.client.post(f"/api/pda/orders/{order_id}/events/", {"events": list(evs)}, format="json")

    def e(self, kind, **kw):
        return {"id": str(uuid.uuid4()), "kind": kind, "at": self.clock.tick(), **kw}

    def test_checker_sees_only_own_orders(self):
        self.login("c1")
        ids = [o["id"] for o in self.client.get("/api/pda/orders/").data]
        self.assertEqual(ids, [self.o1.pk])
        self.assertEqual(self.client.get(f"/api/pda/orders/{self.o2.pk}/").status_code, 404)
        self.assertEqual(self.events(self.o2.pk, self.e("scan", barcode=B1)).status_code, 404)

    def test_double_assignment_rejected(self):
        r = self.client.post(f"/api/orders/{self.o1.pk}/assign/", {"checker_id": self.c2.pk}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (400, "already_assigned"))

    def test_full_check_via_api(self):
        self.login("c1")
        snap = self.client.get(f"/api/pda/orders/{self.o1.pk}/").data
        self.assertEqual(len(snap["lines"]), 2)
        self.assertTrue(all(l["tab"] == "to_check" for l in snap["lines"]))
        r = self.events(self.o1.pk, self.e("scan", barcode=B1), self.e("scan", barcode=B2), self.e("scan", barcode=B1))
        results = [x["result"] for x in r.data["results"]]
        self.assertEqual(results, ["counted", "counted", "over_pending"])
        self.assertEqual(len(r.data["pending"]), 1)
        over_id = r.data["results"][2]["id"]
        p2 = next(l for l in r.data["lines"] if l["product_id"] == "P2")
        r = self.events(self.o1.pk, self.e("extra_decision", ref=over_id, decision="removed"),
                        self.e("declare_short", line_id=p2["id"], reason_id=1))
        tabs = {l["product_id"]: l["tab"] for l in r.data["lines"]}
        self.assertEqual(tabs, {"P1": "issue", "P2": "issue"})
        self.assertEqual(self.client.get(f"/api/pda/orders/{self.o1.pk}/finish-check/").data["problems"], [])
        r = self.client.post(f"/api/pda/orders/{self.o1.pk}/finish/")
        self.assertEqual(r.data["order"]["status"], "completed")
        # supervisor sees the history
        self.login("sup")
        d = self.client.get(f"/api/orders/{self.o1.pk}/").data
        self.assertEqual((d["status"], d["completed_by_name"]), ("completed", "C1"))
        self.assertEqual(self.client.get(f"/api/orders/{self.o1.pk}/events/").data["count"], 5)
        actions = [a["action"] for a in self.client.get(f"/api/orders/{self.o1.pk}/audit/").data["results"]]
        self.assertIn("order.completed", actions)
        self.assertIn("order.assigned", actions)

    def test_panel_summary_checkers_and_audit(self):
        self.login("sup")
        s = self.client.get("/api/orders/summary/").data
        self.assertEqual((s["waiting_assignment"], s["assigned_not_started"]), (0, 2))
        checkers = {c["username"]: c["active_orders"] for c in self.client.get("/api/checkers/").data}
        self.assertEqual(checkers, {"c1": 1, "c2": 1})
        actions = {a["action"] for a in self.client.get("/api/audit/").data["results"]}
        self.assertTrue({"order.imported", "order.assigned", "import.committed"} <= actions)
        self.login("c1")
        self.assertEqual(self.client.get("/api/audit/").status_code, 403)

    def test_barcode_feed_for_pda_cache(self):
        self.login("c1")
        r = self.client.get("/api/pda/barcodes/")
        self.assertEqual({b["product_id"] for b in r.data["barcodes"]}, {"P1", "P2"})
        r2 = self.client.get("/api/pda/barcodes/", {"since": r.data["server_time"].isoformat()})
        self.assertEqual(r2.data["barcodes"], [])
