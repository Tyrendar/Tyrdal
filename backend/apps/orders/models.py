from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.normalize import normalize_text


class Customer(models.Model):
    name = models.CharField(max_length=300)
    name_normalized = models.CharField(max_length=300, unique=True, editable=False)

    def save(self, *args, **kwargs):
        self.name_normalized = normalize_text(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


# --- Import -----------------------------------------------------------------
class ImportKind(models.TextChoices):
    ORDERS = "orders", "Orders"
    BARCODES = "barcodes", "Barcode mapping"


class ImportProfile(models.Model):
    """Maps spreadsheet headers to internal fields so the file layout can change without code changes.

    column_map: {"<internal field>": "<header in file>"}; missing keys fall back
    to a header with the same name as the field. Barcode columns are every
    header matching barcode_column_pattern, so there is no 4-column limit.
    """

    kind = models.CharField(max_length=20, choices=ImportKind.choices)
    name = models.CharField(max_length=100)
    column_map = models.JSONField(default=dict, blank=True)
    barcode_column_pattern = models.CharField(max_length=100, default=r"^barcode\d*$")
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind"], condition=Q(is_default=True), name="one_default_profile_per_kind"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.name}"


class ImportStatus(models.TextChoices):
    VALIDATED = "validated", "Validated (awaiting commit)"
    COMMITTED = "committed", "Committed"
    DISCARDED = "discarded", "Discarded"
    FAILED = "failed", "Failed"


class ImportBatch(models.Model):
    kind = models.CharField(max_length=20, choices=ImportKind.choices)
    file = models.FileField(upload_to="imports/%Y/%m/")
    file_name = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64, db_index=True)
    profile = models.ForeignKey(ImportProfile, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=ImportStatus.choices, default=ImportStatus.VALIDATED)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    committed_at = models.DateTimeField(null=True, blank=True)
    rows_total = models.PositiveIntegerField(default=0)
    rows_error = models.PositiveIntegerField(default=0)
    rows_warning = models.PositiveIntegerField(default=0)
    # File-level problems (missing columns, unreadable file) and the per-order /
    # per-barcode preview shown before commit.
    file_errors = models.JSONField(default=list, blank=True)
    preview = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            models.UniqueConstraint(fields=["file_sha256"], condition=Q(status="committed"), name="uniq_committed_file"),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.file_name} ({self.status})"


class ImportRow(models.Model):
    """Every source row, verbatim, for audit."""

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_no = models.PositiveIntegerField(help_text="1-based Excel row number")
    raw = models.JSONField()
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    order_key = models.CharField(max_length=150, blank=True, db_index=True)

    class Meta:
        ordering = ["batch", "row_no"]


# --- Orders -----------------------------------------------------------------
class OrderStatus(models.TextChoices):
    PENDING_ASSIGNMENT = "pending_assignment", "Pending assignment"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


OPEN_STATUSES = (OrderStatus.PENDING_ASSIGNMENT, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS)


class Order(models.Model):
    reference_type = models.CharField(max_length=60)
    reference_id = models.CharField(max_length=80)
    version = models.PositiveIntegerField(default=1, help_text="Incremented when a re-import replaces the lines")
    content_hash = models.CharField(max_length=64, help_text="Fingerprint of the imported lines; detects changed re-imports")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    picker_name = models.CharField(max_length=150, blank=True, db_index=True)
    source_created_at = models.DateTimeField(null=True, blank=True)
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING_ASSIGNMENT, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    first_scan_at = models.DateTimeField(null=True, blank=True)
    last_scan_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Time actually spent checking: sum of gaps between consecutive actions,
    # ignoring gaps longer than CHECKING["ACTIVE_GAP_SECONDS"] (breaks, waiting
    # for pallets). Set when the order is completed.
    active_seconds = models.PositiveIntegerField(null=True, blank=True)

    # Cached counters (recomputed by the checking engine) so lists and the
    # live board never aggregate 600 lines per row.
    lines_total = models.PositiveIntegerField(default=0)
    lines_done = models.PositiveIntegerField(default=0)
    boxes_ordered = models.PositiveIntegerField(default=0)
    boxes_scanned = models.PositiveIntegerField(default=0)
    open_issues = models.PositiveIntegerField(default=0)
    issues_total = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-source_created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["reference_type", "reference_id"], name="uniq_order_reference"),
        ]

    def __str__(self) -> str:
        return f"{self.reference_id} ({self.customer})"

    @property
    def is_locked(self) -> bool:
        return self.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED)

    @property
    def active_assignment(self):
        return self.assignments.filter(revoked_at__isnull=True).select_related("checker").first()


class LineState(models.TextChoices):
    PENDING = "pending", "Not scanned"
    PARTIAL = "partial", "Partially scanned"
    OK = "ok", "Complete"
    SHORT = "short", "Shortage declared"
    EXTRA = "extra", "Not in order (removed)"


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=500, help_text="Title snapshot at import time")
    aisle_title = models.CharField(max_length=60, blank=True)
    aisle_rank = models.IntegerField(default=0)
    pack_ordered = models.PositiveIntegerField(help_text="Ordered boxes")
    inc_ordered = models.PositiveIntegerField(help_text="Units per box")
    units_ordered = models.PositiveIntegerField()
    packs_picked = models.IntegerField(null=True, blank=True)
    units_picked = models.IntegerField(null=True, blank=True)
    physical_stock = models.IntegerField(null=True, blank=True, help_text="Stock after this order (informational)")
    label = models.CharField(max_length=300, blank=True)
    extra = models.JSONField(default=dict, blank=True, help_text="Unmapped source columns")
    is_unordered = models.BooleanField(default=False, help_text="Created during checking for a product that was not in the order")

    # Checking result. boxes_scanned never exceeds pack_ordered: an over-scan
    # is either removed from the pallet (boxes_extra) or undone as a mistake.
    boxes_scanned = models.PositiveIntegerField(default=0)
    boxes_extra = models.PositiveIntegerField(default=0, help_text="Extra boxes found and removed")
    state = models.CharField(max_length=10, choices=LineState.choices, default=LineState.PENDING, db_index=True)
    last_scan_at = models.DateTimeField(null=True, blank=True)
    row_version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["aisle_rank", "id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="uniq_order_product"),
        ]

    def __str__(self) -> str:
        return f"{self.order.reference_id}/{self.product_id} {self.boxes_scanned}/{self.pack_ordered}"

    @property
    def boxes_short(self) -> int:
        return max(self.pack_ordered - self.boxes_scanned, 0)

    @property
    def units_scanned(self) -> int:
        return self.boxes_scanned * self.inc_ordered


class OrderLineBarcode(models.Model):
    """Barcodes that came with the order file (lookup priority 1). Snapshot; never changed by later mappings."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="+")
    line = models.ForeignKey(OrderLine, on_delete=models.CASCADE, related_name="barcodes")
    code = models.CharField(max_length=64)
    raw = models.CharField(max_length=64)
    is_derived = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["order", "code"])]
        constraints = [models.UniqueConstraint(fields=["line", "code"], name="uniq_line_barcode")]


class Assignment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="assignments")
    checker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    revoke_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            # Database-level guarantee: never two active checkers on one order.
            models.UniqueConstraint(fields=["order"], condition=Q(revoked_at__isnull=True), name="one_active_assignment"),
        ]
        indexes = [models.Index(fields=["checker", "revoked_at"])]

    def __str__(self) -> str:
        return f"{self.order.reference_id} → {self.checker}"
