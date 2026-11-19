import unittest
from decimal import Decimal

from poc_app.installments import installments


class TestInstallments(unittest.TestCase):
    def test_remainder_added_to_first(self):
        self.assertEqual(installments(Decimal("1000"), 3), [Decimal("334"), Decimal("333"), Decimal("333")])

    def test_sum_always_matches_total(self):
        for total in (0, 1, 2, 999, 1000, 12345):
            for times in (1, 2, 3, 7, 12):
                parts = installments(Decimal(total), times)
                self.assertEqual(len(parts), times)
                self.assertEqual(sum(parts), Decimal(total))

    def test_single_payment(self):
        self.assertEqual(installments(Decimal("5000"), 1), [Decimal("5000")])

    def test_invalid_inputs_rejected(self):
        for total, times in ((Decimal("1000"), 0), (Decimal("-1"), 2), (Decimal("10.5"), 2)):
            with self.assertRaises(ValueError):
                installments(total, times)


if __name__ == "__main__":
    unittest.main()
