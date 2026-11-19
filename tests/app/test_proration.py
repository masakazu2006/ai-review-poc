import unittest
from datetime import date
from decimal import Decimal

from poc_app.proration import first_month_fee


class TestFirstMonthFee(unittest.TestCase):
    def test_join_on_first_day_is_full(self):
        self.assertEqual(first_month_fee(Decimal("3000"), date(2026, 4, 1)), Decimal("3000"))

    def test_mid_month(self):
        self.assertEqual(first_month_fee(Decimal("3000"), date(2026, 4, 16)), Decimal("1500"))

    def test_last_day(self):
        self.assertEqual(first_month_fee(Decimal("3100"), date(2026, 1, 31)), Decimal("100"))

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            first_month_fee(Decimal("-1"), date(2026, 4, 1))
