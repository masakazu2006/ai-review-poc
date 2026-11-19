import unittest
from decimal import Decimal

from poc_app.membership import member_fee


class TestMemberFee(unittest.TestCase):
    def test_new_member_pays_full(self):
        self.assertEqual(member_fee(Decimal("12000"), 0), Decimal("12000"))

    def test_long_term_member_discounted(self):
        self.assertEqual(member_fee(Decimal("12000"), 5), Decimal("10800"))

    def test_negative_years_rejected(self):
        with self.assertRaises(ValueError):
            member_fee(Decimal("12000"), -1)


if __name__ == "__main__":
    unittest.main()
