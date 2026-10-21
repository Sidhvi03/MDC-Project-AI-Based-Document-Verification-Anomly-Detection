
import unittest

from app.modules.extraction import (
    extract_fields,
    normalize_amount,
    normalize_date,
)
from app.modules.duplicate_detection import detect_duplicate
from app.modules.validation import validate_fields
from app.modules.decision_engine import decide
from app.modules.anomaly_detection import score_anomaly


class CoreTests(unittest.TestCase):

    def test_extraction(self):
        fields = extract_fields(
            "Invoice no: 12345678\n"
            "Date of issue: 02/23/2021\n"
            "Seller: Alpha Ltd\n"
            "Total: $232.95"
        )
        self.assertEqual(fields["invoice_no"], "12345678")
        self.assertEqual(fields["invoice_date"], "2021-02-23")
        self.assertEqual(fields["total"], 232.95)

    def test_batch1_gross_total_pattern(self):
        text = (
            "SUMMARY VAT Net worth VAT Gross worth "
            "10% 211,77 21,18 232,95 "
            "Total $ 211,77 $ 21,18 $ 232,95"
        )
        fields = extract_fields(text)
        self.assertEqual(fields["total"], 232.95)

    def test_extract_three_summary_amounts(self):
        text = "Total $ 300.26 $ 30.03 $ 330.29"
        fields = extract_fields(text)

        self.assertEqual(fields["net_total"], 300.26)
        self.assertEqual(fields["tax_amount"], 30.03)
        self.assertEqual(fields["total"], 330.29)

    def test_extract_net_tax_gross_with_comma_decimals(self):
        text = "Total $ 300,26 $ 30,03 $ 330,29"
        fields = extract_fields(text)

        self.assertEqual(fields["net_total"], 300.26)
        self.assertEqual(fields["tax_amount"], 30.03)
        self.assertEqual(fields["total"], 330.29)

    def test_single_total_does_not_invent_net_or_tax(self):
        fields = extract_fields(
            "Subtotal $95.00\n"
            "Sales Tax 8% $10.72\n"
            "Shipping & Handling $10.00\n"
            "Total Due $115.72"
        )

        self.assertEqual(fields["total"], 115.72)
        self.assertIsNone(fields["net_total"])
        self.assertIsNone(fields["tax_amount"])

    def test_extract_total_without_currency_symbol(self):
        fields = extract_fields(
            "ID DESCRIPTION QTY PRICE TOTAL\n"
            "1 Activator CREAM 2 126 252\n"
            "2 Permabond 106 1 51 51\n"
            "Total 443\n"
            "TERMS AND CONDITIONS"
        )

        self.assertEqual(fields["gross_total"], 443)
        self.assertEqual(fields["total"], 443)
        self.assertIsNone(fields["net_total"])
        self.assertIsNone(fields["tax_amount"])

    def test_amount_comma_decimal(self):
        self.assertEqual(normalize_amount("1 234,56"), 1234.56)

    def test_amount_us_format(self):
        self.assertEqual(normalize_amount("$1,234.56"), 1234.56)

    def test_amount_european_format(self):
        self.assertEqual(normalize_amount("1.234,56"), 1234.56)

    def test_invalid_amount(self):
        self.assertIsNone(normalize_amount("not an amount"))

    def test_iso_date_normalization(self):
        self.assertEqual(
            normalize_date("2021-02-23"),
            "2021-02-23",
        )

    def test_us_date_normalization(self):
        self.assertEqual(
            normalize_date("02/23/2021"),
            "2021-02-23",
        )

    def test_month_name_date_normalization(self):
        self.assertEqual(
            normalize_date("February 23, 2021"),
            "2021-02-23",
        )

    def test_invalid_date(self):
        self.assertEqual(normalize_date("not a date"), "")

    def test_strong_duplicate(self):
        result = detect_duplicate(
            {"invoice_no": "INV-001", "seller": "Alpha Ltd"},
            [{"id": 1, "invoice_no": "inv001", "seller": "Alpha Ltd"}],
        )
        self.assertEqual(result["status"], "DUPLICATE")

    def test_no_false_strong_duplicate_on_different_seller(self):
        result = detect_duplicate(
            {"invoice_no": "INV-001", "seller": "Alpha Ltd"},
            [{"id": 1, "invoice_no": "INV-001", "seller": "Beta Ltd"}],
        )
        self.assertNotEqual(result["status"], "DUPLICATE")

    def test_anomaly_abstains_without_history(self):
        from unittest.mock import patch

        with patch(
            "app.modules.anomaly_detection.load_reference_totals",
            return_value=[],
        ):
            result = score_anomaly({"total": 100})

        self.assertEqual(result["status"], "NOT_SCORED")

    def test_missing_fields_flag(self):
        result = validate_fields({
            "invoice_no": "",
            "invoice_date": "",
            "seller": "",
            "total": None,
        })
        self.assertFalse(result["valid"])

    def test_zero_total_requires_review(self):
        result = validate_fields({"invoice_no": "A1", "invoice_date": "2021-02-23", "seller": "Alpha Ltd", "total": 0})
        self.assertFalse(result["valid"])
        self.assertTrue(any("zero" in issue.lower() for issue in result["issues"]))

    def test_net_tax_gross_mismatch_requires_review(self):
        result = validate_fields({"invoice_no": "A1", "invoice_date": "2021-02-23", "seller": "Alpha Ltd", "net_total": 100, "tax_amount": 10, "total": 150})
        self.assertFalse(result["valid"])
        self.assertTrue(any("does not approximately equal" in issue for issue in result["issues"]))

    def test_confirmed_duplicate_is_suspicious(self):
        result = decide({"valid": True, "issues": []}, {"status": "DUPLICATE", "reason": "Exact seller/invoice match"}, {"status": "NO_ANOMALY_FLAG"})
        self.assertEqual(result["status"], "SUSPICIOUS")


if __name__ == "__main__":
    unittest.main()
