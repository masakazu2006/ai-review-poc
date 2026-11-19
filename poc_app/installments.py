"""架空の会費精算ツール：分割払いの計算（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

YEN = Decimal("1")


def installments(total: Decimal, times: int) -> list[Decimal]:
    """総額を times 回に分割する。

    各回は円未満切り捨てで計算し、端数は初回に加える。各回の合計は必ず total と一致する。
    total は0円以上の整数円、times は1以上でなければならない。
    """
    if times < 1:
        raise ValueError("times must be >= 1")
    if total < 0 or total != total.quantize(YEN):
        raise ValueError("total must be a non-negative whole-yen amount")
    base = (total / times).quantize(YEN, rounding=ROUND_DOWN)
    first = total - base * (times - 1)
    return [first] + [base] * (times - 1)
