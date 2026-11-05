from __future__ import annotations

from enum import Enum

from django.utils import timezone

from .models import Barcode, Product


class MapResult(str, Enum):
    CREATED = "created"
    UNCHANGED = "unchanged"
    REPLACED = "replaced"  # barcode moved from another product (old row deactivated)
    CONFLICT = "conflict"  # barcode belongs to another product and replace=False


def upsert_product(product_id: str, title: str) -> Product:
    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return Product.objects.create(pk=product_id, title=title)
    if title and product.title != title:
        product.title = title
        product.save(update_fields=["title", "title_normalized", "updated_at"])
    return product


def map_barcode(product: Product, code: str, raw: str, *, source: str, replace: bool, user=None,
                batch=None, derived: bool = False) -> tuple[MapResult, Barcode | None]:
    """Attach canonical `code` to `product` in the central mapping.

    replace=True: a barcode currently owned by another product is moved to this
    one (mapping files are the newest truth). replace=False: keep the existing
    owner and report a conflict (order files must not silently re-point barcodes).
    """
    current = Barcode.objects.select_for_update().filter(code=code, is_active=True).first()
    if current and current.product_id == product.pk:
        return MapResult.UNCHANGED, current
    if current and not replace:
        return MapResult.CONFLICT, current
    result = MapResult.CREATED
    if current:
        current.is_active = False
        current.deactivated_at = timezone.now()
        current.deactivated_by = user
        current.save(update_fields=["is_active", "deactivated_at", "deactivated_by"])
        result = MapResult.REPLACED
    bc = Barcode.objects.create(code=code, raw=raw, product=product, source=source, is_derived=derived,
                                import_batch=batch, created_by=user)
    return result, bc


def lookup(code: str) -> Barcode | None:
    return Barcode.objects.select_related("product").filter(code=code, is_active=True).first()
