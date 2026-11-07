import random

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.orders import autoassign
from apps.orders.autoassign import Checker
from apps.orders.models import Order
from apps.testing import import_orders, line, make_user

B1 = "6260108396830"


def run(orders, caps, loads=None):
    loads = loads or [0] * len(caps)
    cs = [Checker(i + 1, cap, load) for i, (cap, load) in enumerate(zip(caps, loads))]
    autoassign.plan(list(enumerate(orders, start=1)), cs)
    return cs


class PlannerTests(SimpleTestCase):
    def test_user_example_exact_split(self):
        cs = run([1000, 1000, 1500], [2000, 1500])
        self.assertEqual([c.assigned for c in cs], [2000, 1500])

    def test_overflow_is_proportional_to_capacity(self):
        cs = run([600] * 7, [2000, 1500])  # 4200 boxes -> targets 2400 / 1800
        self.assertEqual([round(c.target) for c in cs], [2400, 1800])
        self.assertEqual([c.assigned for c in cs], [2400, 1800])

    def test_under_capacity_nobody_goes_over(self):
        cs = run([300, 250, 200, 150, 100], [2000, 1500])  # 1000 boxes
        for c in cs:
            self.assertLessEqual(c.assigned + c.load, c.capacity)
        self.assertEqual(sum(c.assigned for c in cs), 1000)

    def test_existing_load_counts(self):
        # Checker 1 already has 1000 boxes today: of 2500 new boxes it gets 1000, checker 2 gets 1500.
        cs = run([500] * 5, [2000, 1500], loads=[1000, 0])
        self.assertEqual([c.assigned for c in cs], [1000, 1500])

    def test_close_to_targets_with_uneven_orders(self):
        rnd = random.Random(7)
        orders = [rnd.randint(5, 400) for _ in range(120)]
        cs = run(orders, [2000, 1500, 1200, 800])
        self.assertEqual(sum(c.assigned for c in cs), sum(orders))
        for c in cs:  # within one small order of the target
            self.assertLess(abs(c.assigned - c.target), 60, (c.assigned, c.target))

    def test_every_order_assigned_exactly_once(self):
        cs = run([10, 0, 30, 20], [100, 100, 100])
        ids = sorted(o for c in cs for o, _b in c.orders)
        self.assertEqual(ids, [1, 2, 3, 4])


class AutoAssignApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sup = make_user("sup", "supervisor")
        cls.c1, cls.c2, cls.c3 = make_user("c1"), make_user("c2"), make_user("c3")
        rows = []
        for ref, pack in (("A", 1000), ("B", 1000), ("C", 1500)):
            rows.append(line(ref, "P1", (B1,), pack=pack, inc=1))
        import_orders(rows)

    def setUp(self):
        self.client.force_authenticate(self.sup)

    def test_capacity_plan_edit_apply(self):
        for c, cap in ((self.c1, 2000), (self.c2, 1500)):
            r = self.client.put(f"/api/checkers/{c.pk}/capacity/", {"capacity_boxes": cap}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
        listed = {c["username"]: c for c in self.client.get("/api/checkers/").data}
        self.assertEqual((listed["c1"]["capacity_boxes"], listed["c3"]["capacity_boxes"]), (2000, None))

        plan = self.client.post("/api/orders/auto-assign/plan/", {}, format="json").data
        self.assertEqual(plan["total_boxes"], 3500)
        got = {c["name"]: c["assigned"] for c in plan["checkers"]}
        self.assertEqual(got, {"C1": 2000, "C2": 1500})  # c3 has no capacity: not used
        # Change one by hand before applying.
        pairs = [{"order_id": o["id"], "checker_id": o["checker_id"]} for o in plan["orders"]]
        pairs[0]["checker_id"] = self.c3.pk
        res = self.client.post("/api/orders/auto-assign/apply/", {"assignments": pairs}, format="json").data
        self.assertEqual((len(res["assigned"]), res["failed"]), (3, []))
        self.assertEqual(Order.objects.filter(status="assigned").count(), 3)
        # Applying again: all already assigned.
        again = self.client.post("/api/orders/auto-assign/apply/", {"assignments": pairs}, format="json").data
        self.assertEqual({f["code"] for f in again["failed"]}, {"already_assigned"})
        # Nothing left to plan; today's load now includes the assigned boxes.
        listed = {c["username"]: c for c in self.client.get("/api/checkers/").data}
        self.assertEqual(sum(listed[u]["load_today"] for u in ("c1", "c2", "c3")), 3500)

    def test_needs_capacity_and_permission(self):
        self.assertEqual(self.client.post("/api/orders/auto-assign/plan/", {}, format="json").data["code"], "no_capacity")
        self.assertEqual(self.client.put(f"/api/checkers/{self.sup.pk}/capacity/", {"capacity_boxes": 5}, format="json").data["code"], "invalid_checker")
        self.client.force_authenticate(self.c1)
        self.assertEqual(self.client.post("/api/orders/auto-assign/plan/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/orders/bulk-assign/", {"checker_id": self.c1.pk, "order_ids": []}, format="json").status_code, 403)
