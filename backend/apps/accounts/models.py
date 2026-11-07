from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Codes of the built-in roles. More roles can be created in the panel (AppRole)."""

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


BUILTIN_ROLE_NAMES = {
    Role.ADMIN: ("مدیر سیستم", "Admin"), Role.SUPERVISOR: ("سرپرست", "Supervisor"),
    Role.CHECKER: ("کنترل‌گر", "Checker"), Role.STOCKTAKER: ("انبارگردان", "Stocktaker"),
}
# Permissions that only make sense on the PDA: holding nothing else means no panel access.
PDA_PERMISSIONS = {"checking.perform", "stocktake.perform"}


class AppRole(models.Model):
    """A named set of permissions. Built-in roles cannot be deleted; admin always holds everything."""

    code = models.SlugField(max_length=40, unique=True)
    name_fa = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name_fa or self.code


class User(AbstractUser):
    """A user may hold several roles; permissions are the union of the roles' permissions."""

    roles = models.ManyToManyField(AppRole, blank=True, related_name="users")
    full_name = models.CharField(max_length=150, blank=True)
    language = models.CharField(max_length=5, choices=[("fa", "فارسی"), ("en", "English")], default="fa")

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    def role_codes(self) -> list[str]:
        if not self.pk:
            return []
        return list(self.roles.values_list("code", flat=True))

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or Role.ADMIN in self.role_codes()

    def permission_codes(self) -> set[str]:
        if not self.is_active:
            return set()
        codes = self.role_codes()
        if self.is_superuser or Role.ADMIN in codes:
            return set(PERMISSIONS)
        return set(RolePermission.objects.filter(role__in=codes).values_list("permission", flat=True))

    def has_app_perm(self, code: str) -> bool:
        return code in self.permission_codes()

    def has_role_perm(self, code: str) -> bool:
        """Holds `code` through a role other than admin (admins hold everything but are not checkers/counters)."""
        return self.is_active and RolePermission.objects.filter(
            role__in=[c for c in self.role_codes() if c != Role.ADMIN], permission=code).exists()


def users_with_role_perm(code: str):
    """Active users who hold `code` through a non-admin role (checkers, stocktakers, custom roles)."""
    roles = set(RolePermission.objects.filter(permission=code).values_list("role", flat=True)) - {Role.ADMIN}
    return User.objects.filter(is_active=True, roles__code__in=roles).distinct()


class RolePermission(models.Model):
    role = models.CharField(max_length=40, help_text="AppRole.code")
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
