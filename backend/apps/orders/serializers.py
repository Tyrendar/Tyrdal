from rest_framework import serializers

from apps.checking.models import Discrepancy

from .models import Assignment, ImportBatch, ImportRow, Order, OrderLine


class DiscrepancySerializer(serializers.ModelSerializer):
    reason_code = serializers.CharField(source="reason.code", read_only=True, default=None)

    class Meta:
        model = Discrepancy
        fields = ["id", "type", "qty_boxes", "qty_units", "reason_id", "reason_code", "note", "status",
                  "picker_name", "checker_id", "created_at", "updated_at", "resolved_at"]


class OrderLineSerializer(serializers.ModelSerializer):
    barcodes = serializers.SerializerMethodField()
    discrepancies = DiscrepancySerializer(many=True, read_only=True)
    boxes_short = serializers.IntegerField(read_only=True)
    units_scanned = serializers.IntegerField(read_only=True)
    tab = serializers.SerializerMethodField()

    class Meta:
        model = OrderLine
        fields = ["id", "product_id", "title", "aisle_title", "aisle_rank", "pack_ordered", "inc_ordered",
                  "units_ordered", "packs_picked", "units_picked", "physical_stock", "label", "is_unordered",
                  "boxes_scanned", "boxes_extra", "boxes_short", "units_scanned", "state", "tab", "row_version",
                  "last_scan_at", "barcodes", "discrepancies"]

    def get_barcodes(self, obj):
        return [b.raw for b in obj.barcodes.all() if not b.is_derived]

    def get_tab(self, obj):
        return line_tab(obj)


def line_tab(line: OrderLine) -> str:
    """Which of the three checking tabs the line belongs to: to_check | ok | issue."""
    if line.state in ("pending", "partial"):
        return "to_check"
    if line.state == "ok" and line.boxes_extra == 0:
        return "ok"
    return "issue"


class AssignmentSerializer(serializers.ModelSerializer):
    checker_name = serializers.CharField(source="checker.display_name", read_only=True)
    assigned_by_name = serializers.CharField(source="assigned_by.display_name", read_only=True, default=None)
    revoked_by_name = serializers.CharField(source="revoked_by.display_name", read_only=True, default=None)

    class Meta:
        model = Assignment
        fields = ["id", "checker_id", "checker_name", "assigned_by_name", "assigned_at", "revoked_at",
                  "revoked_by_name", "revoke_reason"]


class OrderListSerializer(serializers.ModelSerializer):
    customer = serializers.CharField(source="customer.name")
    checker = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "reference_type", "reference_id", "version", "customer", "picker_name", "source_created_at",
                  "imported_at", "status", "checker", "lines_total", "lines_done", "boxes_ordered", "boxes_scanned",
                  "open_issues", "issues_total", "progress", "first_scan_at", "last_scan_at", "completed_at",
                  "duration_seconds"]

    def get_checker(self, obj):
        a = next((a for a in obj.assignments.all() if a.revoked_at is None), None)
        return {"id": a.checker_id, "name": a.checker.display_name, "assigned_at": a.assigned_at} if a else None

    def get_progress(self, obj):
        return round(100 * obj.lines_done / obj.lines_total) if obj.lines_total else 0

    def get_duration_seconds(self, obj):
        if obj.first_scan_at and obj.completed_at:
            return int((obj.completed_at - obj.first_scan_at).total_seconds())
        return None


class OrderDetailSerializer(OrderListSerializer):
    assignments = AssignmentSerializer(many=True, read_only=True)
    lines = OrderLineSerializer(many=True, read_only=True)
    completed_by_name = serializers.CharField(source="completed_by.display_name", read_only=True, default=None)

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + ["assignments", "lines", "completed_by_name", "import_batch_id",
                                                    "cancelled_at"]


class ImportBatchSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.display_name", read_only=True, default=None)

    class Meta:
        model = ImportBatch
        fields = ["id", "kind", "file_name", "file_sha256", "status", "uploaded_by_name", "uploaded_at",
                  "committed_at", "rows_total", "rows_error", "rows_warning", "file_errors", "preview", "result"]


class ImportRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportRow
        fields = ["row_no", "order_key", "raw", "errors", "warnings"]
