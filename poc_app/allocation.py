"""架空の会費精算ツール：共通費の按分（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations


def allocate(total: int, weights: list[int]) -> list[int]:
    """総額（円）を重みに比例して按分する（最大剰余法）。

    - 各自の取り分は「総額 × 重み ÷ 重みの合計」の切り捨て。
    - 残った端数の円は、切り捨てで失われた分（剰余）が大きい順に1円ずつ配る。
      剰余が同じ場合は、リストの前にある人を優先する。
    - 結果の合計は必ず total と一致する。重み0の人の取り分は必ず0。
    total は0以上の整数、weights は1件以上の0以上の整数で、合計が正でなければならない。
    """
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError("total must be a non-negative int")
    if not weights:
        raise ValueError("weights must not be empty")
    if any(isinstance(w, bool) or not isinstance(w, int) or w < 0 for w in weights):
        raise ValueError("weights must be non-negative ints")
    weight_sum = sum(weights)
    if weight_sum == 0:
        raise ValueError("sum of weights must be positive")

    shares = [total * w // weight_sum for w in weights]
    remainders = [total * w % weight_sum for w in weights]
    leftover = total - sum(shares)
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in order[:leftover]:
        shares[i] += 1
    return shares
