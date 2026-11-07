from rest_framework.test import APITestCase

from apps.accounts.models import AppRole, RolePermission, User
from apps.testing import make_user


class RoleTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", "admin")
        cls.sup = make_user("sup", "supervisor")

    def test_user_with_two_roles_gets_both_permission_sets(self):
        both = make_user("both", ["checker", "stocktaker"])
        perms = both.permission_codes()
        self.assertTrue({"checking.perform", "stocktake.perform"} <= perms)
        self.client.force_authenticate(both)
        self.assertEqual(self.client.get("/api/pda/orders/").status_code, 200)
        self.assertEqual(self.client.get("/api/pda/stocktakes/").status_code, 200)
        self.client.force_authenticate(self.sup)
        names = {c["username"] for c in self.client.get("/api/checkers/").data}
        self.assertIn("both", names)
        self.assertNotIn("admin", names)  # admins hold everything but are not checkers

    def test_custom_role_lifecycle(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post("/api/roles/", {"name_fa": "ناظر گزارش", "name_en": "Report viewer"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        code = r.data["code"]
        self.assertEqual(code, "report-viewer")
        self.client.put("/api/role-permissions/", {"role": code, "permissions": ["reports.view", "stocktake.manage"]}, format="json")
        self.assertEqual(self.client.get("/api/role-permissions/").data["roles"][code], ["reports.view", "stocktake.manage"])
        r = self.client.post("/api/users/", {"username": "rv", "password": "1234", "roles": [code, "checker"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rv = User.objects.get(username="rv")
        self.assertTrue({"reports.view", "stocktake.manage", "checking.perform"} <= rv.permission_codes())
        self.assertEqual(self.client.delete(f"/api/roles/{AppRole.objects.get(code=code).pk}/").data["code"], "role_in_use")
        self.client.patch(f"/api/users/{rv.pk}/", {"roles": ["checker"]}, format="json")
        self.assertEqual(self.client.delete(f"/api/roles/{AppRole.objects.get(code=code).pk}/").status_code, 204)
        self.assertFalse(RolePermission.objects.filter(role=code).exists())

    def test_builtin_roles_cannot_be_deleted_and_admin_is_fixed(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(f"/api/roles/{AppRole.objects.get(code='checker').pk}/").data["code"], "role_is_builtin")
        r = self.client.put("/api/role-permissions/", {"role": "admin", "permissions": []}, format="json")
        self.assertEqual(r.status_code, 400)
        roles = {r["code"]: r for r in self.client.get("/api/roles/").data}
        self.assertEqual(set(roles), {"admin", "supervisor", "checker", "stocktaker"})
        self.assertTrue(roles["stocktaker"]["is_system"])

    def test_only_admin_grants_admin(self):
        self.sup.roles.add(AppRole.objects.get(code="checker"))
        RolePermission.objects.get_or_create(role="supervisor", permission="users.manage")
        self.client.force_authenticate(self.sup)
        r = self.client.post("/api/users/", {"username": "x", "password": "1234", "roles": ["admin"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.patch(f"/api/users/{self.admin.pk}/", {"full_name": "X"}, format="json").status_code, 403)

    def test_admin_cannot_drop_own_admin_role(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(f"/api/users/{self.admin.pk}/", {"roles": ["supervisor"]}, format="json")
        self.assertEqual(r.data["code"], "cannot_remove_own_admin")

    def test_login_lists_roles(self):
        make_user("two", ["checker", "stocktaker"])
        r = self.client.post("/api/auth/login/", {"username": "two", "password": "pass1234"}, format="json")
        self.assertEqual(sorted(r.data["user"]["roles"]), ["checker", "stocktaker"])
        self.assertIn(r.data["user"]["role"], ("checker", "stocktaker"))  # older PDA versions read one role
