"""Business rules: validation, filtering, summaries and import/export."""
from __future__ import annotations

import csv
import heapq
import json
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .decorators import logged_and_timed
from .models import Transaction
from .repository import BudgetRepository, jsonl_rows
from .validators import (
    BudgetError, positive_int, valid_category, valid_date,
    valid_month, valid_tags, valid_type,
)

CSV_COLUMNS = ["date", "type", "category", "amount", "memo", "tags"]


def fresh_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex.upper()}"


def sort_key(transaction: Transaction) -> tuple[str, str]:
    return (transaction.date, transaction.id)


def latest_stream(source: Iterator[Transaction], *, chunk_size: int = 500,
                  fan_in: int = 32) -> Iterator[Transaction]:
    """Disk-backed descending sort; memory O(chunk_size + fan_in).

    A multi-pass merge caps simultaneously open files at ``fan_in``, even for
    millions of transactions (no full-file list and no unbounded file handles).
    """
    with tempfile.TemporaryDirectory(prefix="budget-sort-") as tmp:
        chunks: list[Path] = []
        batch: list[Transaction] = []

        def spill() -> None:
            if not batch:
                return
            batch.sort(key=sort_key, reverse=True)
            path = Path(tmp) / f"part-{len(chunks):06d}.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for item in batch:
                    f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            chunks.append(path)
            batch.clear()

        def merge_group(paths: list[Path]) -> Iterator[Transaction]:
            streams = [(Transaction.from_dict(data) for data in jsonl_rows(path))
                       for path in paths]
            yield from heapq.merge(*streams, key=sort_key, reverse=True)

        for transaction in source:
            batch.append(transaction)
            if len(batch) >= chunk_size:
                spill()
        if not chunks:
            yield from sorted(batch, key=sort_key, reverse=True)
            return
        spill()

        round_no = 0
        while len(chunks) > fan_in:
            next_round: list[Path] = []
            for index in range(0, len(chunks), fan_in):
                group = chunks[index:index + fan_in]
                path = Path(tmp) / f"merge-{round_no}-{index // fan_in:06d}.jsonl"
                with path.open("w", encoding="utf-8") as f:
                    for item in merge_group(group):
                        f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
                next_round.append(path)
                for old in group:
                    old.unlink()
            chunks = next_round
            round_no += 1
        yield from merge_group(chunks)


@dataclass(frozen=True)
class Summary:
    month: str
    count: int
    income: int
    expense: int
    by_category: dict[str, int]
    budget: int | None

    @property
    def balance(self) -> int:
        return self.income - self.expense


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped: int
    examples: list[str]


class BudgetService:
    def __init__(self, repository: BudgetRepository):
        self.repo = repository

    def categories(self) -> list[str]:
        return sorted(self.repo.categories())

    def require_category(self, name: str) -> str:
        normalized = valid_category(name)
        if normalized not in set(self.repo.categories()):
            raise BudgetError(f"카테고리 '{normalized}'가 없습니다. category list로 확인하거나 category add로 등록하세요.")
        return normalized

    def build_transaction(self, *, date: str, type: str, category: str,
                          amount: object, memo: str = "", tags: object = "") -> Transaction:
        if not isinstance(memo, str):
            raise BudgetError("메모는 문자열이어야 합니다.")
        return Transaction(id=fresh_id("TX"), date=valid_date(date),
                           type=valid_type(type), category=self.require_category(category),
                           amount=positive_int(amount), memo=memo,
                           tags=valid_tags(tags))

    @logged_and_timed
    def add(self, **values: Any) -> Transaction:
        transaction = self.build_transaction(**values)
        self.repo.append_transactions(iter((transaction,)))
        return transaction

    def list_latest(self, limit: int = 20) -> list[Transaction]:
        limit = positive_int(limit, field="limit")
        # Top-N heap uses O(limit) memory, even when file has millions of lines.
        return heapq.nlargest(limit, self.repo.transactions(), key=sort_key)

    def get(self, transaction_id: str) -> Transaction | None:
        return next((t for t in self.repo.transactions() if t.id == transaction_id), None)

    @logged_and_timed
    def update(self, transaction_id: str, changes: dict[str, Any]) -> Transaction:
        allowed = {"date", "type", "category", "amount", "memo", "tags"}
        if not changes or set(changes) - allowed:
            raise BudgetError("변경할 유효한 필드를 1개 이상 지정하세요. update --help를 확인하세요.")
        original = self.get(transaction_id)
        if original is None:
            raise BudgetError(f"없는 데이터: {transaction_id}. list에서 ID를 확인하세요.")
        checked = dict(changes)
        if "date" in checked:
            checked["date"] = valid_date(checked["date"])
        if "type" in checked:
            checked["type"] = valid_type(checked["type"])
        if "category" in checked:
            checked["category"] = self.require_category(checked["category"])
        if "amount" in checked:
            checked["amount"] = positive_int(checked["amount"])
        if "tags" in checked:
            checked["tags"] = valid_tags(checked["tags"])
        modified = Transaction(**{**original.to_dict(), **checked})
        self.repo.rewrite_transactions(
            lambda rows: (modified if row.id == transaction_id else row for row in rows)
        )
        return modified

    @logged_and_timed
    def delete(self, transaction_id: str) -> None:
        if self.get(transaction_id) is None:
            raise BudgetError(f"없는 데이터: {transaction_id}. list에서 ID를 확인하세요.")
        self.repo.rewrite_transactions(
            lambda rows: (row for row in rows if row.id != transaction_id)
        )

    def search(self, *, start: str | None = None, end: str | None = None,
               month: str | None = None, category: str | None = None,
               type: str | None = None, q: str | None = None,
               tag: str | None = None) -> Iterator[Transaction]:
        if start is not None:
            start = valid_date(start)
        if end is not None:
            end = valid_date(end)
        if month is not None:
            month = valid_month(month)
        if start and end and start > end:
            raise BudgetError("시작일(--from)은 종료일(--to)보다 늦을 수 없습니다.")
        if category is not None:
            category = valid_category(category)
        if type is not None:
            type = valid_type(type)
        if tag is not None and not tag.strip():
            raise BudgetError("--tag에 비어 있지 않은 태그를 입력하세요.")

        def matches() -> Iterator[Transaction]:
            for row in self.repo.transactions():
                if start and row.date < start:
                    continue
                if end and row.date > end:
                    continue
                if month and row.date[:7] != month:
                    continue
                if category and row.category != category:
                    continue
                if type and row.type != type:
                    continue
                if q is not None and q.casefold() not in row.memo.casefold():
                    continue
                if tag and tag not in row.tags:
                    continue
                yield row
        return latest_stream(matches())

    @logged_and_timed
    def summary(self, month: str) -> Summary:
        month = valid_month(month)
        count = income = expense = 0
        by_category: dict[str, int] = defaultdict(int)
        for row in self.repo.transactions():
            if row.date[:7] != month:
                continue
            count += 1
            if row.type == "income":
                income += row.amount
            else:
                expense += row.amount
                by_category[row.category] += row.amount
        budget = None
        for entry in self.repo.budgets():
            if entry.get("month") == month:
                budget = positive_int(entry.get("amount"))
        return Summary(month, count, income, expense, dict(by_category), budget)

    @logged_and_timed
    def set_budget(self, month: str, amount: object) -> int:
        month = valid_month(month)
        amount = positive_int(amount)

        def updated() -> Iterator[dict[str, Any]]:
            seen = False
            for row in self.repo.budgets():
                if row.get("month") == month:
                    if not seen:
                        yield {"month": month, "amount": amount}
                        seen = True
                else:
                    yield row
            if not seen:
                yield {"month": month, "amount": amount}
        self.repo.rewrite_budgets(updated())
        return amount

    def add_category(self, name: str) -> str:
        name = valid_category(name)
        categories = self.categories()
        if name in categories:
            raise BudgetError(f"이미 등록된 카테고리입니다: {name}")
        self.repo.rewrite_categories(iter([*categories, name]))
        return name

    def remove_category(self, name: str) -> None:
        name = valid_category(name)
        categories = self.categories()
        if name not in categories:
            raise BudgetError(f"없는 카테고리: {name}. category list로 확인하세요.")
        if len(categories) == 1:
            raise BudgetError("마지막 카테고리는 삭제할 수 없습니다. 기본 카테고리가 재생성되는 것을 방지합니다.")
        if any(row.category == name for row in self.repo.transactions()):
            raise BudgetError(f"'{name}'을(를) 사용한 거래가 있습니다. 해당 거래를 수정/삭제한 후 다시 시도하세요.")
        self.repo.rewrite_categories(c for c in categories if c != name)

    @logged_and_timed
    def import_csv(self, source: Path) -> ImportResult:
        source = Path(source)
        if not source.is_file():
            raise BudgetError(f"CSV 파일이 없습니다: {source}. --from 경로를 확인하세요.")
        valid_categories = set(self.repo.categories())
        skipped = 0
        examples: list[str] = []

        def incoming() -> Iterator[Transaction]:
            nonlocal skipped
            with source.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None or not {"date", "type", "category", "amount"}.issubset(reader.fieldnames):
                    raise BudgetError("CSV 헤더에 date,type,category,amount가 필요합니다. import --help를 확인하세요.")
                for rowno, row in enumerate(reader, 2):
                    try:
                        category = valid_category(row.get("category", ""))
                        if category not in valid_categories:
                            raise BudgetError(f"미등록 카테고리: {category}")
                        yield Transaction(id=fresh_id("TX"),
                                          date=valid_date(row.get("date", "")),
                                          type=valid_type(row.get("type", "")),
                                          category=category,
                                          amount=positive_int(row.get("amount")),
                                          memo=row.get("memo") or "",
                                          tags=valid_tags(row.get("tags") or ""))
                    except BudgetError as exc:
                        skipped += 1
                        if len(examples) < 5:
                            examples.append(f"{rowno}행: {exc}")
        imported = self.repo.append_transactions(incoming())
        return ImportResult(imported, skipped, examples)

    @logged_and_timed
    def export_csv(self, out: Path, *, month: str | None = None,
                   start: str | None = None, end: str | None = None) -> int:
        if month is not None:
            if start is not None or end is not None:
                raise BudgetError("export는 --month 또는 --from/--to 범위 중 하나만 선택하세요.")
            valid_month(month)
        elif start is None or end is None:
            raise BudgetError("export는 --month 또는 --from 및 --to를 모두 지정해야 합니다.")
        # Validate before creating the destination file.
        if start is not None:
            valid_date(start)
        if end is not None:
            valid_date(end)
        if start and end and start > end:
            raise BudgetError("시작일은 종료일보다 늦을 수 없습니다.")
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for item in self.repo.transactions():
                if month is not None and item.date[:7] != month:
                    continue
                if start is not None and item.date < start:
                    continue
                if end is not None and item.date > end:
                    continue
                writer.writerow({"date": item.date, "type": item.type,
                                 "category": item.category, "amount": item.amount,
                                 "memo": item.memo, "tags": ",".join(item.tags)})
                count += 1
        return count
