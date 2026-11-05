"""Test helpers: build order Excel files in memory and create users/orders quickly."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

ORDER_HEADERS = ["reference_id", "created_at", "reference_type", "customer", "picker", "product_id", "barcode1",
                 "barcode2", "barcode3", "barcode4", "title", "aisle_title", "aisle_rank", "pack_ordered",
                 "inc_ordered", "units_ordered", "packs_picked", "units_picked", "physical_stock", "label"]


def line(ref="1001", product="P1", barcodes=("6260108396830",), pack=1, inc=12, units=None, title=None,
         customer="Store A", picker=None, created="2026-11-02 22:12:51", aisle="C-1-1", rank=10, stock=5, **extra):
    row = {
        "reference_id": ref, "created_at": created, "reference_type": "TransferRequest", "customer": customer,
        "picker": picker, "product_id": product, "title": title or f"Product {product}", "aisle_title": aisle,
        "aisle_rank": rank, "pack_ordered": pack, "inc_ordered": inc,
        "units_ordered": pack * inc if units is None else units, "packs_picked": 0, "units_picked": 0,
        "physical_stock": stock, "label": None,
    }
    for i, b in enumerate(barcodes, start=1):
        row[f"barcode{i}"] = b
    row.update(extra)
    return row


def xlsx_bytes(rows: list[dict], headers: list[str] | None = None) -> bytes:
    headers = list(headers or ORDER_HEADERS)
    for r in rows:
        for k in r:
            if k not in headers:
                headers.append(k)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Query result"
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(rows, name="orders.xlsx", headers=None) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, xlsx_bytes(rows, headers),
                              content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def make_user(username, role="checker", password="pass1234"):
    from apps.accounts.models import User

    u = User.objects.create_user(username=username, password=password, role=role, full_name=username.title())
    return u


def import_orders(rows, user=None):
    """Validate + commit an order file through the real import service. Returns the committed batch."""
    from apps.orders.importing import commit_order_batch, sha256_of, validate_order_batch
    from apps.orders.models import ImportBatch

    f = upload(rows, name=f"orders-{uuid.uuid4().hex[:6]}.xlsx")
    batch = ImportBatch.objects.create(kind="orders", file=f, file_name=f.name, file_sha256=sha256_of(f), uploaded_by=user)
    batch = validate_order_batch(batch)
    assert batch.status == "validated", batch.file_errors
    return commit_order_batch(batch, user)


class Clock:
    """Monotonic fake PDA clock for event timestamps."""

    def __init__(self, start: datetime | None = None):
        self.t = start or timezone.now() - timedelta(hours=1)

    def tick(self, ms: int = 2000) -> str:
        self.t += timedelta(milliseconds=ms)
        return self.t.isoformat()


def ev(kind, clock: Clock, ms=2000, **fields) -> dict:
    return {"id": str(uuid.uuid4()), "kind": kind, "at": clock.tick(ms), **fields}
