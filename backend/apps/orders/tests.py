from django.test import TestCase

from apps.catalog.models import Barcode
from apps.catalog.normalize import canonical
from apps.testing import Clock, ev, import_orders, line, make_user, upload, xlsx_bytes

from . import services
from .importing import FileProblem, commit_barcode_batch, commit_order_batch, sha256_of, validate_barcode_batch, validate_order_batch
from .models import ImportBatch, Order, OrderLine, OrderLineBarcode, OrderStatus


def validate(rows, kind="orders", headers=None, name="f.xlsx"):
    f = upload(rows, name=name, headers=headers)
    b = ImportBatch.objects.create(kind=kind, file=f, file_name=name, file_sha256=sha256_of(f))
    return validate_barcode_batch(b) if kind == "barcodes" else validate_order_batch(b)


class OrderImportValidationTests(TestCase):
    def test_multi_order_file_groups_by_reference(self):
        rows = [line("1", "P1"), line("1", "P2", ("6260055843500",), pack=5, inc=6), line("2", "P1", customer="Store B")]
        b = validate(rows)
        self.assertEqual(b.status, "validated")
        orders = {o["reference_id"]: o for o in b.preview["orders"]}
        self.assertEqual(orders["1"]["lines"], 2)
        self.assertEqual(orders["1"]["boxes"], 6)
        self.assertEqual(orders["2"]["action"], "new")

    def test_units_must_equal_pack_times_inc(self):
        b = validate([line("1", "P1", pack=2, inc=12, units=12)])
        row = b.rows.get()
        self.assertEqual(row.errors[0]["code"], "units_mismatch")
        self.assertEqual(row.errors[0]["expected"], 24)
        self.assertEqual(b.preview["orders"][0]["action"], "invalid")

    def test_required_and_type_errors(self):
        no_title = line("1", "P2", ("6260055843500",))
        no_title["title"] = ""
        b = validate([line("1", "P1", pack="abc", units=12), no_title])
        codes = [e["code"] for r in b.rows.all() for e in r.errors]
        self.assertEqual(sorted(codes), ["not_integer", "required"])

    def test_missing_required_column_is_file_error(self):
        headers = ["reference_id", "customer", "product_id", "barcode1", "title", "pack_ordered", "inc_ordered"]
        row = {k: v for k, v in line("1", "P1").items() if k in headers}
        b = validate([row], headers=headers)
        self.assertEqual(b.status, "failed")
        self.assertEqual(b.file_errors[0]["field"], "units_ordered")

    def test_duplicate_product_in_order_and_header_mismatch(self):
        b = validate([line("1", "P1"), line("1", "P1"), line("1", "P2", ("6260055843500",), customer="Other")])
        codes = sorted(e["code"] for r in b.rows.all() for e in r.errors)
        self.assertEqual(codes, ["duplicate_product_in_order", "order_header_mismatch"])

    def test_unlimited_barcode_columns(self):
        rows = [line("1", "P1", ("6260108396830",), barcode5="6261149047200", barcode9="6261149047910")]
        import_orders(rows)
        codes = set(OrderLineBarcode.objects.values_list("code", flat=True))
        self.assertEqual(codes, {canonical("6260108396830"), canonical("6261149047200"), canonical("6261149047910")})

    def test_bad_barcodes_are_warnings_not_errors(self):
        b = validate([line("1", "P1", ("6260055843500", "123456", "626017023008"))])
        self.assertEqual(b.rows_error, 0)
        codes = sorted(w["code"] for w in b.rows.get().warnings)
        self.assertEqual(codes, ["barcode_truncated_ean", "barcode_unusable"])

    def test_repair_never_shadows_another_products_real_barcode(self):
        # Real data, order 16639: 11596 lists "261182000552"; "6"+that is 11590's real barcode.
        b = validate([line("1", "11596", ("6261182000477", "261182000552")), line("1", "11590", ("6261182000552",))])
        w = [x for x in b.rows.get(row_no=2).warnings if x["code"] == "barcode_repair_skipped"]
        self.assertEqual(w[0]["belongs_to"], ["11590"])
        commit_order_batch(b, None)
        owners = set(OrderLineBarcode.objects.filter(code=canonical("6261182000552")).values_list("line__product_id", flat=True))
        self.assertEqual(owners, {"11590"})

    def test_unknown_columns_kept_as_extra(self):
        import_orders([line("1", "P1", warehouse_zone="Z9")])
        self.assertEqual(OrderLine.objects.get().extra, {"warehouse_zone": "Z9"})

    def test_column_profile_maps_renamed_headers(self):
        from .models import ImportProfile

        p = ImportProfile.objects.get(kind="orders", is_default=True)
        p.column_map = {"pack_ordered": "Boxes"}
        p.save()
        r = line("1", "P1", pack=3, inc=4)
        r["Boxes"] = r.pop("pack_ordered")
        headers = [h for h in r if not h.startswith("barcode")] + ["barcode1"]
        b = validate([r], headers=headers)
        self.assertEqual(b.status, "validated", b.file_errors)
        self.assertEqual(b.preview["orders"][0]["boxes"], 3)


class OrderImportCommitTests(TestCase):
    def setUp(self):
        self.sup = make_user("sup", "supervisor")
        self.checker = make_user("chk")

    def test_commit_creates_orders_lines_barcodes_and_mapping(self):
        rows = [line("1", "P1", ("6260108396830", "626017023008")), line("1", "P2", ("6260055843500",), pack=5, inc=6)]
        batch = import_orders(rows, self.sup)
        order = Order.objects.get(reference_id="1")
        self.assertEqual(order.status, OrderStatus.PENDING_ASSIGNMENT)
        self.assertEqual((order.lines_total, order.boxes_ordered), (2, 6))
        # truncated barcode stored with its repaired variant, and both feed the central mapping
        self.assertTrue(Barcode.objects.filter(code=canonical("6260170230087"), product_id="P1", is_derived=True).exists())
        self.assertEqual(batch.result["orders"]["new"], ["1"])
        self.assertEqual(batch.rows.count(), 2)  # original rows preserved

    def test_same_file_cannot_be_committed_twice(self):
        rows = [line("1", "P1")]
        data = xlsx_bytes(rows)
        from django.core.files.uploadedfile import SimpleUploadedFile

        b1 = ImportBatch.objects.create(kind="orders", file=SimpleUploadedFile("a.xlsx", data), file_name="a.xlsx",
                                        file_sha256="x" * 64)
        commit_order_batch(validate_order_batch(b1), self.sup)
        b2 = ImportBatch.objects.create(kind="orders", file=SimpleUploadedFile("a.xlsx", data), file_name="a.xlsx",
                                        file_sha256="x" * 64)
        validate_order_batch(b2)
        with self.assertRaises(FileProblem):
            commit_order_batch(b2, self.sup)

    def test_reimport_unchanged_is_skipped(self):
        import_orders([line("1", "P1")])
        b = validate([line("1", "P1")], name="again.xlsx")
        self.assertEqual(b.preview["orders"][0]["action"], "unchanged")

    def test_reimport_with_picker_updates_info_only(self):
        import_orders([line("1", "P1")])
        batch = import_orders([line("1", "P1", picker="Ali", stock=0)])
        self.assertEqual(batch.result["orders"]["info_updated"], ["1"])
        o = Order.objects.get()
        self.assertEqual((o.picker_name, o.version), ("Ali", 1))
        self.assertEqual(o.lines.get().physical_stock, 0)

    def test_changed_order_replaced_before_checking_starts(self):
        import_orders([line("1", "P1"), line("1", "P2", ("6260055843500",))])
        order = Order.objects.get()
        services.assign(order, self.checker, by=self.sup)
        import_orders([line("1", "P1", pack=3, inc=12)])
        order.refresh_from_db()
        self.assertEqual(order.version, 2)
        self.assertEqual(order.lines.count(), 1)
        self.assertEqual(order.status, OrderStatus.ASSIGNED)

    def test_changed_order_blocked_after_checking_started(self):
        from apps.checking import engine

        import_orders([line("1", "P1", pack=2)])
        order = Order.objects.get()
        services.assign(order, self.checker, by=self.sup)
        engine.process_events(order.pk, self.checker, [ev("scan", Clock(), barcode="6260108396830")])
        b = validate([line("1", "P1", pack=3, inc=12)], name="changed.xlsx")
        self.assertEqual(b.preview["orders"][0]["action"], "blocked_started")
        commit_order_batch(b, self.sup)
        order.refresh_from_db()
        self.assertEqual((order.version, order.lines.get().pack_ordered), (1, 2))

    def test_order_barcode_never_repoints_existing_mapping(self):
        import_orders([line("1", "P1", ("6260108396830",))])
        batch = import_orders([line("2", "P9", ("6260108396830",))])
        self.assertEqual(Barcode.objects.get(code=canonical("6260108396830"), is_active=True).product_id, "P1")
        self.assertEqual(batch.result["mapping_conflicts"][0]["mapped_product_id"], "P1")


class BarcodeMappingImportTests(TestCase):
    HEAD = ["product_id", "barcode", "title"]

    def test_create_replace_and_history(self):
        import_orders([line("1", "P1", ("6260108396830",))])
        rows = [{"product_id": "P2", "barcode": "6260108396830", "title": "New owner"},
                {"product_id": "P2", "barcode": "6261149047200", "title": "New owner"},
                {"product_id": "P3", "barcode": "123", "title": "x"}]
        b = validate(rows, kind="barcodes", headers=self.HEAD)
        self.assertEqual(b.preview["actions"], {"replace": 1, "create": 1})
        self.assertEqual(b.rows_error, 1)  # P3 has no usable barcode
        commit_barcode_batch(b, None)
        active = Barcode.objects.get(code=canonical("6260108396830"), is_active=True)
        self.assertEqual(active.product_id, "P2")
        self.assertTrue(Barcode.objects.filter(code=canonical("6260108396830"), product_id="P1", is_active=False).exists())
        # existing order keeps its own barcode snapshot
        self.assertEqual(OrderLineBarcode.objects.get(code=canonical("6260108396830")).line.product_id, "P1")

    def test_same_barcode_two_products_in_file_is_error(self):
        rows = [{"product_id": "P1", "barcode": "6260108396830", "title": "a"},
                {"product_id": "P2", "barcode": "6260108396830", "title": "b"}]
        b = validate(rows, kind="barcodes", headers=self.HEAD)
        self.assertEqual(b.rows_error, 2)

    def test_new_product_needs_title(self):
        b = validate([{"product_id": "P7", "barcode": "6260108396830", "title": None}], kind="barcodes", headers=self.HEAD)
        self.assertEqual(b.rows.get().errors[0]["code"], "title_required_for_new_product")


class AssignmentTests(TestCase):
    def setUp(self):
        self.sup = make_user("sup", "supervisor")
        self.c1, self.c2 = make_user("c1"), make_user("c2")
        import_orders([line("1", "P1")])
        self.order = Order.objects.get()

    def test_single_active_checker(self):
        from apps.accounts.errors import DomainError

        services.assign(self.order, self.c1, by=self.sup)
        with self.assertRaises(DomainError) as e:
            services.assign(self.order, self.c2, by=self.sup)
        self.assertEqual(e.exception.error_code, "already_assigned")

    def test_reassign_keeps_history(self):
        services.assign(self.order, self.c1, by=self.sup)
        services.reassign(self.order, self.c2, by=self.sup, reason="shift change")
        self.assertEqual(self.order.assignments.count(), 2)
        self.assertEqual(self.order.active_assignment.checker, self.c2)
        self.assertEqual(self.order.assignments.get(checker=self.c1).revoke_reason, "shift change")

    def test_cannot_assign_to_non_checker(self):
        from apps.accounts.errors import DomainError

        with self.assertRaises(DomainError):
            services.assign(self.order, self.sup, by=self.sup)
