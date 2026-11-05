import os

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User


class Command(BaseCommand):
    help = "Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD if no admin exists (idempotent)."

    def handle(self, **_):
        if User.objects.filter(role=Role.ADMIN, is_active=True).exists():
            self.stdout.write("admin exists")
            return
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            self.stderr.write("ADMIN_PASSWORD not set; skipping admin creation")
            return
        User.objects.create_superuser(username=username, password=password, role=Role.ADMIN, full_name="Administrator", email="")
        self.stdout.write(self.style.SUCCESS(f"admin '{username}' created"))
