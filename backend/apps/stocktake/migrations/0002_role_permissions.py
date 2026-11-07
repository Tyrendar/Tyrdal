from django.db import migrations

GRANTS = {"admin": ["stocktake.manage", "stocktake.perform"], "supervisor": ["stocktake.manage"],
          "stocktaker": ["stocktake.perform"]}


def grant(apps, schema_editor):
    """Existing installs: role permissions are only seeded into an empty table, so add the new ones."""
    RolePermission = apps.get_model("accounts", "RolePermission")
    if not RolePermission.objects.exists():
        return  # fresh install: the post_migrate seed creates everything
    for role, perms in GRANTS.items():
        for p in perms:
            RolePermission.objects.get_or_create(role=role, permission=p)


class Migration(migrations.Migration):
    dependencies = [("stocktake", "0001_initial"), ("accounts", "0002_alter_rolepermission_permission_and_more")]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
