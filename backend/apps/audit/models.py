from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only record of every important action. Never updated or deleted."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    device = models.ForeignKey("accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ip = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=60, db_index=True)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    # Lets the order detail page show every action touching an order, including
    # actions on its lines, assignments and discrepancies.
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} {self.action} {self.entity_type}:{self.entity_id}"
