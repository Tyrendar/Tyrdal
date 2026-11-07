"""Stocktaking: a vendor is counted on a date by one or more counters.

Each counter scans a barcode and types the counted quantity (units) and, optionally,
a price. The same barcode may be recorded many times (several locations, several
counters); the WMS export sums them per barcode.
"""
import uuid

from django.conf import settings
from django.db import models


class Vendor(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class StocktakeStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class Stocktake(models.Model):
    """One vendor counted from `date` until closed."""

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="stocktakes")
    date = models.DateField(db_index=True, help_text="Counting may start on this (warehouse-local) date")
    counters = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="stocktakes", blank=True)
    status = models.CharField(max_length=10, choices=StocktakeStatus.choices, default=StocktakeStatus.OPEN, db_index=True)
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.vendor} {self.date}"


class StockCount(models.Model):
    """One counter's entry: barcode + quantity (+ price). The id is generated on the PDA,
    so a re-sent batch updates instead of duplicating; edits/deletes carry the PDA's
    `client_updated_at` and an older write never overwrites a newer one."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    stocktake = models.ForeignKey(Stocktake, on_delete=models.CASCADE, related_name="counts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey("accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    barcode = models.CharField(max_length=64, help_text="As scanned (scanner noise removed); exported as-is")
    code = models.CharField(max_length=64, db_index=True, help_text="Canonical key used to sum the same barcode")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    counted_at = models.DateTimeField()
    client_updated_at = models.DateTimeField()
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["counted_at"]
        indexes = [models.Index(fields=["stocktake", "code"]), models.Index(fields=["stocktake", "user"])]
