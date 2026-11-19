"""架空の会費精算ツール：入会月の日割り（PoC用ダミー。実在のデータ・計算とは無関係）。"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_DOWN, Decimal

YEN = Decimal("1")


def first_month_fee(monthly_fee: Decimal, join_date: date) -> Decimal:
    """入会月の会費を返す。月の途中で入会した場合は日割りとし、円未満は切り捨てる。1日に入会した場合は満額。"""
    if monthly_fee < 0:
        raise ValueError("monthly_fee must be >= 0")
    days_in_month = calendar.monthrange(join_date.year, join_date.month)[1]
    remaining_days = days_in_month - join_date.day + 1
    return (monthly_fee * remaining_days / days_in_month).quantize(YEN, rounding=ROUND_DOWN)
