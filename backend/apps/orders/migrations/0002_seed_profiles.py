from django.db import migrations


def seed(apps, schema_editor):
    Profile = apps.get_model("orders", "ImportProfile")
    # Empty column_map = headers in the file have the same names as the fields
    # (the layout of the provided order_check export).
    Profile.objects.get_or_create(kind="orders", name="Order check export (default)",
                                  defaults={"column_map": {}, "barcode_column_pattern": r"^barcode\d*$", "is_default": True})
    Profile.objects.get_or_create(kind="barcodes", name="Barcode mapping (product_id, barcode, title)",
                                  defaults={"column_map": {}, "barcode_column_pattern": r"^barcode\d*$", "is_default": True})


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
