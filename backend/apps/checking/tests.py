from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.errors import DomainError
from apps.catalog.models import Barcode, Product
from apps.catalog.normalize import canonical
from apps.orders import services
from apps.orders.models import LineState, Order, OrderStatus
from apps.testing import Clock, ev, import_orders, line, make_user

from . import engine
from .models import CheckEvent, Discrepancy, DiscrepancyReason, DiscrepancyStatus, EventResult

B1, B2, B3, B_OTHER = "6260108396830", "6260055843500", "6260113899210", "6262754015370"


class EngineTestBase(TestCase):
    def setUp(self):
        self.sup = make_user("sup", "supervisor")
        self.checker = make_user("chk")
        import_orders([
            line("1", "P1", (B1,), pack=1, inc=12, rank=30),
            line("1", "P2", (B2,), pack=3, inc=6, rank=10),
            line("1", "P3", (B3,), pack=2, inc=24, rank=20),
        ])
        # A product that exists in the central mapping but is not in order 1.
        import_orders([line("99", "PX", (B_OTHER,), customer="Other store")])
        self.order = Order.objects.get(reference_id="1")
        a = services.assign(self.order, self.checker, by=self.sup)
        self.clock = Clock(start=a.assigned_at)

    def send(self, *events, user=None):
        return engine.process_events(self.order.pk, user or self.checker, list(events))["results"]

    def scan(self, barcode, ms=2000, user=None):
        return self.send(ev("scan", self.clock, ms, barcode=barcode), user=user)[0]

    def line(self, product_id):
        return self.order.lines.get(product_id=product_id)

    def reason(self, code):
        return DiscrepancyReason.objects.get(code=code)


class ScanTests(EngineTestBase):
    def test_one_scan_is_one_box_and_completes_line(self):
        r = self.scan(B1)
        self.assertEqual(r["result"], EventResult.COUNTED)
        l = self.line("P1")
        self.assertEqual((l.boxes_scanned, l.state, l.units_scanned), (1, LineState.OK, 12))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)
        self.assertIsNotNone(self.order.first_scan_at)

    def test_multi_box_line_partial_then_ok(self):
        self.scan(B2)
        self.assertEqual(self.line("P2").state, LineState.PARTIAL)
        self.scan(B2)
        self.scan(B2)
        self.assertEqual((self.line("P2").boxes_scanned, self.line("P2").state), (3, LineState.OK))

    def test_double_read_flagged_by_pda_is_recorded_not_counted(self):
        self.scan(B2)
        r = self.send(ev("scan", self.clock, 150, barcode=B2, duplicate=True))[0]
        self.assertEqual((r["result"], r["line_id"]), (EventResult.DUPLICATE, self.line("P2").pk))
        self.assertEqual(self.line("P2").boxes_scanned, 1)

    def test_fast_consecutive_boxes_all_count(self):
        # Server never re-decides debounce from timestamps (clock skew safe).
        for _ in range(3):
            self.assertEqual(self.scan(B2, ms=0)["result"], EventResult.COUNTED)
        self.assertEqual(self.line("P2").boxes_scanned, 3)

    def test_pda_clock_skew_corrected_with_sent_at(self):
        skew = timedelta(hours=3)  # PDA clock 3 h ahead
        pda_now = timezone.now() + skew
        e = {"id": str(__import__("uuid").uuid4()), "kind": "scan", "at": (pda_now - timedelta(seconds=30)).isoformat(), "barcode": B1}
        r = engine.process_events(self.order.pk, self.checker, [e], sent_at=pda_now.isoformat())["results"][0]
        at = CheckEvent.objects.get(pk=r["id"]).client_at
        self.assertLess(abs((timezone.now() - timedelta(seconds=30) - at).total_seconds()), 5)

    def test_any_order_and_any_variant_of_the_barcode(self):
        self.scan("0" + B3)  # GTIN-14 form of the same code
        self.scan(" " + B1 + "\n")
        self.assertEqual(self.line("P3").boxes_scanned, 1)
        self.assertEqual(self.line("P1").boxes_scanned, 1)

    def test_central_mapping_used_when_not_in_order_file(self):
        p1 = Product.objects.get(pk="P1")
        Barcode.objects.create(code=canonical("6269999999992"), raw="6269999999992", product=p1, source="manual")
        r = self.scan("6269999999992")
        self.assertEqual((r["result"], r["line_id"]), (EventResult.COUNTED, self.line("P1").pk))
        self.assertEqual(CheckEvent.objects.get(pk=r["id"]).match_source, "mapping")

    def test_unknown_barcode(self):
        r = self.scan("1234567890123")
        self.assertEqual(r["result"], EventResult.UNKNOWN)

    def test_replayed_batch_is_not_counted_twice(self):
        e = ev("scan", self.clock, barcode=B2)
        self.send(e)
        r = self.send(e)[0]
        self.assertTrue(r["replay"])
        self.assertEqual(self.line("P2").boxes_scanned, 1)


class ExtraTests(EngineTestBase):
    def test_over_scan_is_pending_and_blocks_further_scans(self):
        self.scan(B1)
        over = self.scan(B1)
        self.assertEqual(over["result"], EventResult.OVER_PENDING)
        self.assertEqual(self.line("P1").boxes_scanned, 1)  # never counted
        self.assertEqual(self.scan(B2)["result"], EventResult.BLOCKED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.open_issues, 1)

    def test_removed_extra_recorded_with_default_reason(self):
        self.scan(B1)
        over = self.scan(B1)
        d = self.send(ev("extra_decision", self.clock, ref=over["id"], decision="removed"))[0]
        self.assertEqual(d["result"], EventResult.REMOVED)
        l = self.line("P1")
        self.assertEqual((l.boxes_scanned, l.boxes_extra, l.state), (1, 1, LineState.OK))
        disc = Discrepancy.objects.get(line=l)
        self.assertEqual((disc.type, disc.qty_boxes, disc.qty_units), ("extra", 1, 12))
        self.assertEqual((disc.reason.code, disc.status), ("extra_item", DiscrepancyStatus.REASONED))
        self.assertEqual(self.scan(B2)["result"], EventResult.COUNTED)  # unblocked

    def test_mistake_records_nothing(self):
        self.scan(B1)
        over = self.scan(B1)
        self.send(ev("extra_decision", self.clock, ref=over["id"], decision="mistake"))
        self.assertFalse(Discrepancy.objects.exists())
        self.assertEqual(self.line("P1").boxes_extra, 0)

    def test_decision_only_once(self):
        self.scan(B1)
        over = self.scan(B1)
        self.send(ev("extra_decision", self.clock, ref=over["id"], decision="removed"))
        r = self.send(ev("extra_decision", self.clock, ref=over["id"], decision="removed"))[0]
        self.assertEqual(r["error"], "already_decided")
        self.assertEqual(self.line("P1").boxes_extra, 1)

    def test_not_in_order_product_tracked_for_picker_report(self):
        self.order.picker_name = "Reza"
        self.order.save()
        r = self.scan(B_OTHER)
        self.assertEqual(r["result"], EventResult.NOT_IN_ORDER_PENDING)
        self.send(ev("extra_decision", self.clock, ref=r["id"], decision="removed"))
        l = self.order.lines.get(product_id="PX")
        self.assertTrue(l.is_unordered)
        self.assertEqual((l.state, l.boxes_extra, l.pack_ordered), (LineState.EXTRA, 1, 0))
        d = Discrepancy.objects.get(line=l)
        self.assertEqual((d.type, d.reason.code, d.picker_name), ("not_in_order", "not_in_order", "Reza"))
        # PDA created this line offline (no server id yet) and names it by product.
        r = self.send(ev("set_reason", self.clock, line_id=-1, product_id="PX", type="not_in_order",
                         reason_id=self.reason("picking_error").pk))[0]
        self.assertEqual(r["result"], EventResult.APPLIED)
        d.refresh_from_db()
        self.assertEqual(d.reason.code, "picking_error")
        # second box of the same wrong product: pending again, same line
        r2 = self.scan(B_OTHER)
        self.send(ev("extra_decision", self.clock, ref=r2["id"], decision="removed"))
        d.refresh_from_db()
        self.assertEqual(d.qty_boxes, 2)
        self.order.refresh_from_db()
        self.assertEqual(self.order.lines_total, 3)  # unordered line does not count as an order line


class ShortageTests(EngineTestBase):
    def test_declare_short_with_reason(self):
        self.scan(B2)
        r = self.send(ev("declare_short", self.clock, line_id=self.line("P2").pk, reason_id=self.reason("no_stock").pk))[0]
        self.assertEqual(r["result"], EventResult.APPLIED)
        l = self.line("P2")
        d = l.discrepancies.get()
        self.assertEqual((l.state, d.qty_boxes, d.qty_units, d.status), (LineState.SHORT, 2, 12, DiscrepancyStatus.REASONED))

    def test_short_without_reason_is_open_until_reason_set(self):
        lid = self.line("P3").pk
        self.send(ev("declare_short", self.clock, line_id=lid))
        self.assertEqual(self.line("P3").discrepancies.get().status, DiscrepancyStatus.OPEN)
        self.send(ev("set_reason", self.clock, line_id=lid, type="short", reason_id=self.reason("no_stock").pk))
        self.assertEqual(self.line("P3").discrepancies.get().status, DiscrepancyStatus.REASONED)

    def test_reason_requiring_note(self):
        lid = self.line("P3").pk
        self.send(ev("declare_short", self.clock, line_id=lid, reason_id=self.reason("other").pk))
        self.assertEqual(self.line("P3").discrepancies.get().status, DiscrepancyStatus.OPEN)
        self.send(ev("set_reason", self.clock, line_id=lid, type="short", reason_id=self.reason("other").pk, note="box torn"))
        self.assertEqual(self.line("P3").discrepancies.get().status, DiscrepancyStatus.REASONED)

    def test_reason_must_apply_to_type(self):
        r = self.send(ev("declare_short", self.clock, line_id=self.line("P3").pk, reason_id=self.reason("extra_item").pk))[0]
        self.assertEqual(r["error"], "reason_not_applicable")

    def test_late_boxes_shrink_and_resolve_shortage(self):
        lid = self.line("P2").pk
        self.send(ev("declare_short", self.clock, line_id=lid, reason_id=self.reason("no_stock").pk))
        self.scan(B2)
        self.scan(B2)
        d = self.line("P2").discrepancies.get()
        self.assertEqual((d.qty_boxes, self.line("P2").state), (1, LineState.SHORT))
        self.scan(B2)
        d.refresh_from_db()
        self.assertEqual((d.status, self.line("P2").state), (DiscrepancyStatus.RESOLVED, LineState.OK))

    def test_adjust_corrects_quantity_and_is_audited(self):
        self.scan(B2)
        self.scan(B2)
        self.send(ev("adjust", self.clock, line_id=self.line("P2").pk, boxes=1, note="scanned wrong pallet"))
        self.assertEqual(self.line("P2").boxes_scanned, 1)
        self.assertTrue(self.order.audit_entries.filter(action="line.adjusted").exists())
        r = self.send(ev("adjust", self.clock, line_id=self.line("P2").pk, boxes=9))[0]
        self.assertEqual(r["error"], "invalid_quantity")


class CompletionTests(EngineTestBase):
    def finish(self):
        return engine.finish(self.order.pk, self.checker)

    def test_cannot_finish_with_unchecked_lines(self):
        self.scan(B1)
        with self.assertRaises(DomainError) as e:
            self.finish()
        codes = {p["code"] for p in e.exception.data["problems"]}
        self.assertEqual(codes, {"line_not_checked"})

    def test_cannot_finish_with_pending_decision_or_open_discrepancy(self):
        for b in (B1, B2, B2, B2, B3, B3):
            self.scan(b)
        over = self.scan(B1)
        with self.assertRaises(DomainError) as e:
            self.finish()
        self.assertEqual(e.exception.data["problems"][0]["code"], "pending_decision")
        self.send(ev("extra_decision", self.clock, ref=over["id"], decision="removed"))
        self.assertEqual(self.finish().status, OrderStatus.COMPLETED)

    def test_full_flow_with_shortage_then_locked(self):
        for b in (B1, B2, B2, B3):
            self.scan(b)
        self.send(ev("declare_short", self.clock, line_id=self.line("P2").pk))
        self.send(ev("declare_short", self.clock, line_id=self.line("P3").pk, reason_id=self.reason("no_stock").pk))
        with self.assertRaises(DomainError):
            self.finish()  # P2 shortage has no reason
        self.send(ev("set_reason", self.clock, line_id=self.line("P2").pk, type="short", reason_id=self.reason("no_stock").pk))
        order = self.finish()
        self.assertEqual((order.status, order.completed_by, order.lines_done, order.issues_total),
                         (OrderStatus.COMPLETED, self.checker, 3, 2))
        self.assertEqual(self.scan(B2)["result"], EventResult.LOCKED)
        self.assertEqual(self.line("P2").boxes_scanned, 2)

    def test_only_assigned_checker_can_finish(self):
        other = make_user("other")
        with self.assertRaises(DomainError):
            engine.finish(self.order.pk, other)


class AssignmentEventTests(EngineTestBase):
    def test_unassigned_user_events_rejected(self):
        other = make_user("other")
        r = self.scan(B1, user=other)
        self.assertEqual(r["error"], "not_assigned")
        self.assertEqual(self.line("P1").boxes_scanned, 0)

    def test_offline_events_before_reassignment_are_kept(self):
        new = make_user("new")
        offline_scan = ev("scan", self.clock, ms=1, barcode=B2)  # happened on old PDA before reassignment
        services.reassign(self.order, new, by=self.sup, reason="break")
        self.clock.t = timezone.now() + timedelta(seconds=1)
        r = self.send(offline_scan)[0]
        self.assertEqual(r["result"], EventResult.COUNTED)
        self.assertTrue(CheckEvent.objects.get(pk=r["id"]).is_late)
        # but anything after the reassignment is refused
        after = ev("scan", self.clock, barcode=B2)
        self.assertEqual(self.send(after)[0]["error"], "not_assigned")
        self.assertEqual(self.scan(B2, user=new)["result"], EventResult.COUNTED)
        self.assertEqual(self.line("P2").boxes_scanned, 2)
