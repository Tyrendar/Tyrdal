from django.apps import AppConfig
from django.db.models.signals import post_migrate


def seed_role_permissions(sender, **kwargs):
    from .models import DEFAULT_ROLE_PERMISSIONS, RolePermission

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
