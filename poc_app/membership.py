"""架空の会費精算ツール：継続会員の割引（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

YEN = Decimal("1")
DISCOUNT_RATE = Decimal("0.10")
LOYALTY_YEARS = 3


def member_fee(base_fee: Decimal, years: int) -> Decimal:
    """年会費を返す。在籍3年以上の会員は10%割引（円未満切り捨て）。"""
    if years < 0:
        raise ValueError("years must be >= 0")
    if years > LOYALTY_YEARS:
        return (base_fee * (1 - DISCOUNT_RATE)).quantize(YEN, rounding=ROUND_DOWN)
    return base_fee
