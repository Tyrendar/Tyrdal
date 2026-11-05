import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.orders.importing import (
    FileProblem, commit_barcode_batch, commit_order_batch, sha256_of, validate_barcode_batch, validate_order_batch,
)
from apps.orders.models import ImportBatch, ImportKind, ImportStatus


class Command(BaseCommand):
    help = "Validate (and optionally commit) an order or barcode-mapping Excel file from the command line."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--kind", choices=ImportKind.values, default=ImportKind.ORDERS)
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--user", help="username recorded as uploader")
        parser.add_argument("--show", type=int, default=10, help="problem rows to print")

    def handle(self, path, kind, commit, user, show, **_):
        p = Path(path)
        if not p.exists():
            raise CommandError(f"{p} not found")
        uploader = User.objects.filter(username=user).first() if user else None
        with p.open("rb") as fh:
            digest = sha256_of(fh)
            batch = ImportBatch.objects.create(kind=kind, file=File(fh, name=p.name), file_name=p.name,
                                               file_sha256=digest, uploaded_by=uploader)
        batch = validate_barcode_batch(batch) if kind == ImportKind.BARCODES else validate_order_batch(batch)
        out = {k: getattr(batch, k) for k in ("id", "status", "rows_total", "rows_error", "rows_warning", "file_errors")}
        out["preview"] = {k: v for k, v in batch.preview.items() if k != "headers"}
        self.stdout.write(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        for row in batch.rows.exclude(errors=[], warnings=[])[:show]:
            self.stdout.write(f"row {row.row_no}: errors={row.errors} warnings={row.warnings}")
        if commit:
            if batch.status != ImportStatus.VALIDATED:
                raise CommandError("batch is not committable")
            try:
                batch = commit_barcode_batch(batch, uploader) if kind == ImportKind.BARCODES else commit_order_batch(batch, uploader)
            except FileProblem as e:
                raise CommandError(json.dumps(e.payload))
            self.stdout.write(self.style.SUCCESS(json.dumps(batch.result, ensure_ascii=False, default=str)))
