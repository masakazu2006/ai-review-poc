import itertools
import unittest

from poc_app.allocation import allocate


class TestAllocate(unittest.TestCase):
    def test_even_split_with_leftover(self):
        self.assertEqual(allocate(100, [1, 1, 1]), [34, 33, 33])

    def test_largest_remainder_wins(self):
        self.assertEqual(allocate(10, [1, 2]), [3, 7])          # 3.33 / 6.66 → 端数1円は剰余の大きい2人目

    def test_zero_weight_gets_nothing(self):
        self.assertEqual(allocate(5, [0, 1, 1]), [0, 3, 2])

    def test_sum_and_bounds_exhaustive(self):
        for total in range(0, 60):
            for weights in itertools.product(range(0, 4), repeat=3):
                if sum(weights) == 0:
                    continue
                shares = allocate(total, list(weights))
                self.assertEqual(sum(shares), total)
                for s, w in zip(shares, weights):
                    exact = total * w / sum(weights)
                    self.assertTrue(int(exact) <= s <= int(exact) + 1)
                    if w == 0:
                        self.assertEqual(s, 0)

    def test_invalid_inputs(self):
        for total, weights in ((-1, [1]), (10, []), (10, [0, 0]), (10, [1, -1]), (1.5, [1]), (True, [1])):
            with self.assertRaises(ValueError):
                allocate(total, weights)
