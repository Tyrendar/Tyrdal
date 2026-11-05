"""Barcode and text normalization.

The exact same rules are implemented in the PDA app (Kotlin). Every barcode is
reduced to a *canonical code* both when it is imported and when it is scanned,
so lookups are a plain equality match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
_GS1_AIM = {"]C1", "]e0", "]d2", "]Q3", "]J1"}
_CONTROL_OR_SPACE = re.compile(r"[\s\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
GS = "\x1d"


def gtin_check_digit(body: str) -> int:
    """Check digit for a GTIN body (all digits except the check digit)."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def is_valid_gtin(code: str) -> bool:
    return code.isdigit() and len(code) in (8, 12, 13, 14) and gtin_check_digit(code[:-1]) == int(code[-1])


def clean(raw: str) -> str:
    """Strip scanner noise: AIM prefix, GS1 element string, whitespace, control and bidi chars."""
    if raw is None:
        return ""
    s = str(raw).translate(_DIGITS).strip()
    aim = s[:3]
    if _AIM_PREFIX.match(s):
        s = s[3:]
    is_gs1 = aim in _GS1_AIM or GS in s
    if is_gs1 and s.startswith("01") and len(s) >= 16 and s[2:16].isdigit():
        s = s[2:16]  # AI (01) = GTIN-14
    s = _CONTROL_OR_SPACE.sub("", s)
    # Excel sometimes turns numeric barcodes into floats ("6260108396830.0").
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def canonical(raw: str) -> str:
    """Canonical lookup key.

    GTIN-12/13/14 are left-padded to 14 digits so that a UPC-A read as 12
    digits, the same code read as EAN-13 with a leading zero, and a GTIN-14
    with leading zeros all map to the same key. Everything else is kept as-is
    (upper-cased).
    """
    s = clean(raw)
    if s.isdigit() and 12 <= len(s) <= 14:
        return s.zfill(14)
    return s.upper()


@dataclass(frozen=True)
class BarcodeCheck:
    raw: str
    code: str  # canonical, "" when unusable
    problem: str | None  # None = OK; otherwise a stable warning code
    derived: tuple[str, ...] = ()  # extra canonical codes that should also map to the product


def inspect_import_barcode(raw, *, min_length: int = 8, blocklist: frozenset[str] = frozenset()) -> BarcodeCheck:
    """Validate a barcode coming from an import file.

    Returns problem codes:
      - "too_short"     placeholder like 123456; not usable
      - "blocklisted"   explicitly configured junk value
      - "repeated_digit" e.g. 0000000000000
      - "truncated_ean" 12 digits that look like an EAN-13 missing its check
                        digit; the computed 13-digit code is added as derived.
    """
    s = clean(raw)
    if not s:
        return BarcodeCheck(str(raw or ""), "", "empty")
    if s in blocklist:
        return BarcodeCheck(s, "", "blocklisted")
    if len(s) < min_length:
        return BarcodeCheck(s, "", "too_short")
    if len(set(s)) == 1:
        return BarcodeCheck(s, "", "repeated_digit")
    code = canonical(s)
    if s.isdigit() and len(s) == 12 and (not is_valid_gtin(s) or s.startswith("626")):
        # The source system sometimes drops one digit of an EAN-13. Two
        # repairs are seen in real data (Iranian GS1 prefix is 626):
        #   626017023008  → check digit dropped  → 6260170230087
        #   261182000552  → leading "6" dropped  → 6261182000552
        derived = [canonical(s + str(gtin_check_digit(s)))]
        if is_valid_gtin("6" + s):
            derived.insert(0, canonical("6" + s))
        return BarcodeCheck(s, code, "truncated_ean", tuple(derived))
    return BarcodeCheck(s, code, None)


# --- Text -------------------------------------------------------------------
_TEXT_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا", "ؤ": "و",
    "‌": " ", "‍": "", "ـ": "",
})
_SPACES = re.compile(r"\s+")


def normalize_text(s: str | None) -> str:
    """Search key for Persian/English text: unify Arabic/Persian letters and digits, fold case and spaces."""
    if not s:
        return ""
    return _SPACES.sub(" ", str(s).translate(_DIGITS).translate(_TEXT_MAP).lower()).strip()
