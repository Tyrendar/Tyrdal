import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ReasonAppliesTo(models.TextChoices):
    SHORT = "short", "Shortage"
    EXTRA = "extra", "Extra / not in order"
    BOTH = "both", "Both"


class ReasonCategory(models.TextChoices):
    STOCK = "stock", "Stock"
    PICKING = "picking", "Picking"
    SCANNING = "scanning", "Scanning"
    OTHER = "other", "Other"


class ReasonDefaultFor(models.TextChoices):
    EXTRA = "extra", "Extra box of an ordered product"
    NOT_IN_ORDER = "not_in_order", "Product not in the order"


class DiscrepancyReason(models.Model):
    """Configurable reasons. Nothing in the apps hardcodes a reason; the
    automatic reason used when a checker removes an extra box is whichever
    reason is marked `default_for`."""

    code = models.SlugField(max_length=50, unique=True)
    name_fa = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    applies_to = models.CharField(max_length=10, choices=ReasonAppliesTo.choices, default=ReasonAppliesTo.BOTH)
    category = models.CharField(max_length=10, choices=ReasonCategory.choices, default=ReasonCategory.OTHER)
    requires_note = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    default_for = models.CharField(max_length=20, choices=ReasonDefaultFor.choices, null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["default_for"], condition=Q(default_for__isnull=False), name="one_default_reason_per_kind"),
        ]

    def __str__(self) -> str:
        return self.name_en

    def applies(self, discrepancy_type: str) -> bool:
        if self.applies_to == ReasonAppliesTo.BOTH:
            return True
        if self.applies_to == ReasonAppliesTo.SHORT:
            return discrepancy_type == DiscrepancyType.SHORT
        return discrepancy_type in (DiscrepancyType.EXTRA, DiscrepancyType.NOT_IN_ORDER)


class EventKind(models.TextChoices):
    SCAN = "scan", "Scan"
    EXTRA_DECISION = "extra_decision", "Decision on an extra / not-in-order scan"
    DECLARE_SHORT = "declare_short", "Declare shortage"
    SET_REASON = "set_reason", "Set discrepancy reason"
    ADJUST = "adjust", "Correct scanned quantity"


class EventResult(models.TextChoices):
    COUNTED = "counted", "Box counted"
    DUPLICATE = "duplicate", "Ignored: scanner double-read"
    OVER_PENDING = "over_pending", "More than ordered — awaiting decision"
    NOT_IN_ORDER_PENDING = "not_in_order_pending", "Not in order — awaiting decision"
    UNKNOWN = "unknown", "Unknown barcode"
    BLOCKED = "blocked", "Rejected: a decision is pending"
    LOCKED = "locked", "Rejected: order completed or cancelled"
    REMOVED = "removed", "Extra box removed from pallet"
    MISTAKE = "mistake", "Scan was a mistake"
    APPLIED = "applied", "Applied"
    INVALID = "invalid", "Rejected: invalid request"


PENDING_RESULTS = (EventResult.OVER_PENDING, EventResult.NOT_IN_ORDER_PENDING)


class CheckEvent(models.Model):
    """Append-only log of everything a checker does on an order.

    The id is generated on the PDA, so a batch re-sent after a network error is
    recognised and never applied twice.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="events")
    line = models.ForeignKey("orders.OrderLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assignment = models.ForeignKey("orders.Assignment", null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="check_events")
    device = models.ForeignKey("accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=20, choices=EventKind.choices)
    result = models.CharField(max_length=24, choices=EventResult.choices)
    barcode_raw = models.CharField(max_length=128, blank=True)
    barcode_code = models.CharField(max_length=64, blank=True, db_index=True)
    match_source = models.CharField(max_length=10, blank=True, help_text="order | mapping | ''")
    delta_boxes = models.IntegerField(default=0)
    ref_event = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="decisions")
    payload = models.JSONField(default=dict, blank=True)
    client_at = models.DateTimeField(help_text="When it happened on the PDA")
    received_at = models.DateTimeField(auto_now_add=True)
    is_late = models.BooleanField(default=False, help_text="Accepted from a checker whose assignment was revoked after the event happened")

    class Meta:
        ordering = ["client_at", "received_at"]
        indexes = [
            models.Index(fields=["order", "client_at"]),
            models.Index(fields=["user", "client_at"]),
            models.Index(fields=["order", "user", "barcode_code", "client_at"]),
        ]


class DiscrepancyType(models.TextChoices):
    SHORT = "short", "Shortage"
    EXTRA = "extra", "Extra boxes (removed)"
    NOT_IN_ORDER = "not_in_order", "Product not in order (removed)"


class DiscrepancyStatus(models.TextChoices):
    OPEN = "open", "Needs reason"
    REASONED = "reasoned", "Recorded with reason"
    RESOLVED = "resolved", "Resolved (no longer a discrepancy)"


class Discrepancy(models.Model):
    line = models.ForeignKey("orders.OrderLine", on_delete=models.CASCADE, related_name="discrepancies")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="discrepancies")
    type = models.CharField(max_length=15, choices=DiscrepancyType.choices)
    qty_boxes = models.PositiveIntegerField(default=0)
    qty_units = models.PositiveIntegerField(default=0)
    reason = models.ForeignKey(DiscrepancyReason, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=DiscrepancyStatus.choices, default=DiscrepancyStatus.OPEN, db_index=True)
    # Snapshots for reporting even if the order is later reassigned.
    picker_name = models.CharField(max_length=150, blank=True, db_index=True)
    checker = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["line", "type"], name="uniq_line_discrepancy_type")]
