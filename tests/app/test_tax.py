import unittest
from decimal import Decimal

from poc_app.tax import tax_amount, tax_included


class TestTax(unittest.TestCase):
    def test_round_numbers(self):
        self.assertEqual(tax_included(Decimal("100")), Decimal("110"))
        self.assertEqual(tax_included(Decimal("1000")), Decimal("1100"))

    def test_zero(self):
        self.assertEqual(tax_included(Decimal("0")), Decimal("0"))

    def test_fraction_rounded(self):
        self.assertEqual(tax_included(Decimal("105")), Decimal("116"))   # 115.5 → 116

    def test_tax_amount(self):
        self.assertEqual(tax_amount(Decimal("1000")), Decimal("100"))

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            tax_included(Decimal("-1"))
