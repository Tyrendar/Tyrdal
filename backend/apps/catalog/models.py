from django.conf import settings
from django.db import models
from django.db.models import Q

from .normalize import normalize_text


class Product(models.Model):
    # Source-system product_id. Kept as text so a future source with
    # non-numeric ids needs no migration.
    id = models.CharField(max_length=64, primary_key=True)
    title = models.CharField(max_length=500)
    title_en = models.CharField(max_length=500, blank=True)
    title_normalized = models.CharField(max_length=500, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.title_normalized = normalize_text(f"{self.title} {self.title_en}")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.id} {self.title}"


class BarcodeSource(models.TextChoices):
    ORDER_IMPORT = "order_import", "Order import"
    MAPPING_FILE = "mapping_file", "Mapping file"
    MANUAL = "manual", "Manual"


class Barcode(models.Model):
    """Central barcode → product mapping, reused by all orders.

    A barcode is never deleted; when it moves to another product the old row is
    deactivated (history) and a new active row is created.
    """

    code = models.CharField(max_length=64, help_text="Canonical code used for lookup")
    raw = models.CharField(max_length=64, help_text="Value as it appeared in the source")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="barcodes")
    source = models.CharField(max_length=20, choices=BarcodeSource.choices)
    is_derived = models.BooleanField(default=False, help_text="Computed variant, e.g. EAN-13 rebuilt from a 12-digit code")
    is_active = models.BooleanField(default=True)
    import_batch = models.ForeignKey("orders.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code"], condition=Q(is_active=True), name="uniq_active_barcode"),
        ]
        indexes = [models.Index(fields=["code"]), models.Index(fields=["product", "is_active"])]

    def __str__(self) -> str:
        return f"{self.raw} → {self.product_id}{'' if self.is_active else ' (inactive)'}"
