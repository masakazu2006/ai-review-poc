import unittest
from decimal import Decimal

from poc_app.settlement import average_payment, is_valid_amount, split_fee


class TestSettlement(unittest.TestCase):
    def test_split_fee(self):
        self.assertEqual(split_fee(Decimal("1000"), 3), (Decimal("333"), Decimal("1")))

    def test_split_fee_invalid_members(self):
        with self.assertRaises(ValueError):
            split_fee(Decimal("1000"), 0)

    def test_is_valid_amount_boundary(self):
        self.assertTrue(is_valid_amount(Decimal("100000")))
        self.assertFalse(is_valid_amount(Decimal("100001")))
        self.assertFalse(is_valid_amount(Decimal("-1")))

    def test_average_payment(self):
        self.assertEqual(average_payment([Decimal("100"), Decimal("201")]), Decimal("150"))
        self.assertEqual(average_payment([]), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
