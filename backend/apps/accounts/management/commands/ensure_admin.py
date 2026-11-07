import os

from django.core.management.base import BaseCommand

from apps.accounts.models import AppRole, Role, User


class Command(BaseCommand):
    help = "Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD if no admin exists (idempotent)."

    def handle(self, **_):
        if User.objects.filter(roles__code=Role.ADMIN, is_active=True).exists():
            self.stdout.write("admin exists")
            return
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            self.stderr.write("ADMIN_PASSWORD not set; skipping admin creation")
            return
        user = User.objects.create_superuser(username=username, password=password, full_name="Administrator", email="")
        admin_role, _ = AppRole.objects.get_or_create(code=Role.ADMIN, defaults={"name_fa": "مدیر سیستم", "name_en": "Admin", "is_system": True})
        user.roles.add(admin_role)
        self.stdout.write(self.style.SUCCESS(f"admin '{username}' created"))
