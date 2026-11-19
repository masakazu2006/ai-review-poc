"""架空の会費精算ツール：消費税の計算（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations

from decimal import Decimal

YEN = Decimal("1")
TAX_RATE = Decimal("0.10")


def tax_included(net: Decimal) -> Decimal:
    """税抜金額から税込金額を返す。税率10%、円未満は四捨五入。"""
    if net < 0:
        raise ValueError("net must be >= 0")
    return (net * (1 + TAX_RATE)).quantize(YEN)


def tax_amount(net: Decimal) -> Decimal:
    """税抜金額に対する消費税額（税込金額 − 税抜金額）を返す。"""
    return tax_included(net) - net
