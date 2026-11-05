from django.db import migrations

# Initial reasons from the requirements. They are ordinary rows: admins can
# rename, deactivate or add reasons in the panel.
REASONS = [
    # code, fa, en, applies_to, category, requires_note, default_for
    ("no_stock", "موجودی فیزیکی ندارد", "No physical stock", "short", "stock", False, None),
    ("extra_item", "کالای اضافه", "Extra item", "extra", "picking", False, "extra"),
    ("not_in_order", "کالای خارج از سفارش", "Item not in order", "extra", "picking", False, "not_in_order"),
    ("duplicate_scan", "اسکن تکراری", "Duplicate scan", "both", "scanning", False, None),
    ("picking_error", "خطای جمع‌آوری", "Picking error", "both", "picking", False, None),
    ("incorrect_quantity", "تعداد نادرست", "Incorrect quantity", "both", "picking", False, None),
    ("damaged", "کالای آسیب‌دیده", "Damaged item", "short", "stock", False, None),
    ("other", "سایر", "Other", "both", "other", True, None),
]


def seed(apps, schema_editor):
    Reason = apps.get_model("checking", "DiscrepancyReason")
    for i, (code, fa, en, applies, cat, note, default_for) in enumerate(REASONS):
        Reason.objects.get_or_create(code=code, defaults=dict(
            name_fa=fa, name_en=en, applies_to=applies, category=cat, requires_note=note,
            default_for=default_for, sort_order=(i + 1) * 10,
        ))


class Migration(migrations.Migration):
    dependencies = [("checking", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
