"""Plain console output of transactions (no column-width formatting)."""
from __future__ import annotations

from collections.abc import Iterable
from .models import Transaction


def print_transactions(records: Iterable[Transaction]) -> int:
    count = 0
    for item in records:
        print(f"{item.id} | {item.date} | {item.type} | {item.category} | "
              f"{item.amount} | {item.memo} | {','.join(item.tags)}")
        count += 1
    if count == 0:
        print("데이터 없음")
    return count
