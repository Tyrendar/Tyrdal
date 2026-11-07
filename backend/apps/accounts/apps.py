from django.apps import AppConfig
from django.db.models.signals import post_migrate


def seed_role_permissions(sender, **kwargs):
    from .models import BUILTIN_ROLE_NAMES, DEFAULT_ROLE_PERMISSIONS, AppRole, RolePermission

    for code, (fa, en) in BUILTIN_ROLE_NAMES.items():
        AppRole.objects.get_or_create(code=code, defaults={"name_fa": fa, "name_en": en, "is_system": True})

    if RolePermission.objects.exists():
        return
    RolePermission.objects.bulk_create(
        RolePermission(role=role, permission=perm)
        for role, perms in DEFAULT_ROLE_PERMISSIONS.items()
        for perm in sorted(perms)
    )


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        post_migrate.connect(seed_role_permissions, sender=self)
