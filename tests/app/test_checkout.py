import unittest
from decimal import Decimal

from poc_app.checkout import cart_lines, subtotal_with_tax, to_tax_included


class TestCheckout(unittest.TestCase):
    def test_to_tax_included(self):
        self.assertEqual(to_tax_included(Decimal("1000")), Decimal("1100"))

    def test_cart_lines(self):
        catalog = {"T001": Decimal("1100"), "B002": Decimal("550")}
        self.assertEqual(cart_lines({"T001": 2}, catalog), [(Decimal("1100"), 2)])

    def test_cart_lines_rejects_zero_quantity(self):
        with self.assertRaises(ValueError):
            cart_lines({"T001": 0}, {"T001": Decimal("1100")})

    def test_subtotal_with_tax(self):
        self.assertEqual(subtotal_with_tax([(Decimal("1000"), 2), (Decimal("500"), 1)]), Decimal("2750"))
