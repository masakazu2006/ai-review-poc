"""架空の会費精算ツール：物販の会計（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

YEN = Decimal("1")
TAX_RATE = Decimal("0.10")


def to_tax_included(net_price: Decimal) -> Decimal:
    """税抜価格を税込価格にする（円未満切り捨て）。"""
    return (net_price * (1 + TAX_RATE)).quantize(YEN, rounding=ROUND_DOWN)


def cart_lines(cart: dict[str, int], catalog: dict[str, Decimal]) -> list[tuple[Decimal, int]]:
    """カートの商品コードと数量から、(単価, 数量) の明細行を作る。

    catalog は商品コード → 店頭表示価格（税込）。
    """
    lines = []
    for sku, qty in cart.items():
        if qty <= 0:
            raise ValueError(f"invalid quantity for {sku}")
        lines.append((catalog[sku], qty))
    return lines


def subtotal_with_tax(lines: list[tuple[Decimal, int]]) -> Decimal:
    """(税抜単価, 数量) の明細行から、税込の小計を返す。"""
    return sum((to_tax_included(price) * qty for price, qty in lines), Decimal("0"))


def checkout_total(cart: dict[str, int], catalog: dict[str, Decimal]) -> Decimal:
    """会計の支払総額（税込）を返す。"""
    return subtotal_with_tax(cart_lines(cart, catalog))
