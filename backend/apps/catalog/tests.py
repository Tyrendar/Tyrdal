from django.test import SimpleTestCase

from .normalize import canonical, clean, inspect_import_barcode, is_valid_gtin, normalize_text


class CanonicalTests(SimpleTestCase):
    def test_ean13_and_gtin14_and_upca_variants_match(self):
        self.assertEqual(canonical("6260108396830"), canonical("06260108396830"))
        # UPC-A read as 12 digits vs EAN-13 with leading zero
        self.assertEqual(canonical("012000800443"), canonical("0012000800443"))

    def test_scanner_noise_is_removed(self):
        self.assertEqual(clean(" 6260108396830\r\n"), "6260108396830")
        self.assertEqual(clean("]E06260108396830"), "6260108396830")  # AIM symbology prefix
        self.assertEqual(clean("⁦6260108396830⁩"), "6260108396830")  # bidi isolates from RTL UI
        self.assertEqual(clean("۶۲۶۰۱۰۸۳۹۶۸۳۰"), "6260108396830")  # Persian digits
        self.assertEqual(clean("6260108396830.0"), "6260108396830")  # Excel float

    def test_gs1_element_string_extracts_gtin(self):
        self.assertEqual(clean("]C10106260108396830\x1d10ABC"), "06260108396830")

    def test_internal_codes_kept_exact(self):
        self.assertEqual(canonical("2162231168480006"), "2162231168480006")
        self.assertEqual(canonical("11201045"), "11201045")


class InspectImportBarcodeTests(SimpleTestCase):
    def test_placeholder_rejected(self):
        self.assertEqual(inspect_import_barcode("123456").problem, "too_short")
        self.assertEqual(inspect_import_barcode("0000000000000").problem, "repeated_digit")
        self.assertEqual(inspect_import_barcode("99999999", blocklist=frozenset({"99999999"})).problem, "blocklisted")

    def test_truncated_check_digit_repaired(self):
        chk = inspect_import_barcode("626017023008")
        self.assertEqual(chk.problem, "truncated_ean")
        self.assertIn(canonical("6260170230087"), chk.derived)
        self.assertTrue(is_valid_gtin("6260170230087"))

    def test_dropped_leading_six_repaired(self):
        chk = inspect_import_barcode("261182000552")
        self.assertIn(canonical("6261182000552"), chk.derived)

    def test_valid_upca_untouched(self):
        chk = inspect_import_barcode("012000800443")
        self.assertIsNone(chk.problem)
        self.assertEqual(chk.derived, ())


class TextTests(SimpleTestCase):
    def test_arabic_letters_unified(self):
        self.assertEqual(normalize_text("شيرين عسل كيك"), normalize_text("شیرین عسل کیک"))
        self.assertEqual(normalize_text("Ultra  HOLD ۱۵۰"), "ultra hold 150")
