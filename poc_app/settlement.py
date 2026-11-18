"""架空の「会費精算ツール」（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

YEN = Decimal("1")


def split_fee(total: Decimal, members: int) -> tuple[Decimal, Decimal]:
    """会費を人数で割り、1人あたりの額（円未満切り捨て）と端数を返す。"""
    if members <= 0:
        raise ValueError("members must be positive")
    per_head = (total / members).quantize(YEN, rounding=ROUND_DOWN)
    remainder = total - per_head * members
    return per_head, remainder


def is_valid_amount(amount: Decimal, upper: Decimal = Decimal("100000")) -> bool:
    """0円以上、上限以下なら有効（上限ちょうどは有効）。"""
    return Decimal("0") <= amount <= upper


def average_payment(payments: list[Decimal]) -> Decimal:
    """支払額の平均（円未満切り捨て）。空の場合は0。"""
    if not payments:
        return Decimal("0")
    return (sum(payments, Decimal("0")) / len(payments)).quantize(YEN, rounding=ROUND_DOWN)
