from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    SUPERVISOR = "supervisor", "Supervisor"
    CHECKER = "checker", "Checker"
    STOCKTAKER = "stocktaker", "Stocktaker"


# Catalogue of permission codes the application checks. Which role holds which
# permission is data (RolePermission) so admins can change it without a deploy.
PERMISSIONS: dict[str, str] = {
    "users.manage": "Create, edit, deactivate users and reset passwords",
    "permissions.manage": "Change which role holds which permission",
    "reasons.manage": "Create, edit, activate/deactivate discrepancy reasons",
    "orders.view": "View orders, lines and checking progress",
    "orders.import": "Upload and commit order Excel files",
    "orders.assign": "Assign and reassign orders to checkers",
    "orders.manage": "Cancel and reopen orders",
    "barcodes.manage": "Upload barcode mapping files and edit mappings",
    "reports.view": "Access reports and live monitoring",
    "audit.view": "View the audit log",
    "checking.perform": "Check assigned orders on the PDA",
    "stocktake.manage": "Manage vendors and stocktakes, export counts",
    "stocktake.perform": "Count stock on the PDA",
}

DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN: set(PERMISSIONS),
    Role.SUPERVISOR: {
        "orders.view", "orders.import", "orders.assign", "orders.manage",
        "reasons.manage", "barcodes.manage", "reports.view", "audit.view", "stocktake.manage",
    },
    Role.CHECKER: {"checking.perform"},
    Role.STOCKTAKER: {"stocktake.perform"},
}


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CHECKER, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    language = models.CharField(max_length=5, choices=[("fa", "فارسی"), ("en", "English")], default="fa")

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    def permission_codes(self) -> set[str]:
        if not self.is_active:
            return set()
        if self.role == Role.ADMIN or self.is_superuser:
            return set(PERMISSIONS)
        return set(RolePermission.objects.filter(role=self.role).values_list("permission", flat=True))

    def has_app_perm(self, code: str) -> bool:
        return code in self.permission_codes()


class RolePermission(models.Model):
    role = models.CharField(max_length=20, choices=Role.choices)
    permission = models.CharField(max_length=50, choices=[(k, k) for k in PERMISSIONS])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission")]

    def __str__(self) -> str:
        return f"{self.role}:{self.permission}"


class Device(models.Model):
    """A PDA. Identified by the serial/Android ID the app reports at login."""

    serial = models.CharField(max_length=100, unique=True)
    model = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=30, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    def __str__(self) -> str:
        return f"{self.model} {self.serial}".strip()
