"""JSONL persistence: generators for reading, ordinary full rewrite for editing."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from .models import Transaction
from .validators import BudgetError

DEFAULT_CATEGORIES = ("food", "transport", "housing", "salary", "shopping", "health", "leisure", "other")


def jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Decode one JSON object at a time without loading the whole file."""
    with path.open("r", encoding="utf-8") as f:
        for index, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("JSON 객체여야 함")
                yield item
            except (ValueError, UnicodeError) as exc:
                raise BudgetError(f"저장 파일 손상: {path.name}:{index} ({exc}). 파일 내용을 확인하세요.") from exc


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Ordinary whole-file rewrite, without rename-based replacement."""
    # Evaluate the source *before* opening the destination for truncation.
    # This lets callers pass generators reading the same file.
    values = list(rows)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in values:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


class BudgetRepository:
    """All persistent file operations; validation rules belong to the service."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.transactions_file = self.data_dir / "transactions.jsonl"
        self.categories_file = self.data_dir / "categories.jsonl"
        self.budgets_file = self.data_dir / "budgets.jsonl"
        for path in self.data_files():
            path.touch(exist_ok=True)
        if self.categories_file.stat().st_size == 0:
            write_jsonl(self.categories_file, ({"name": v} for v in DEFAULT_CATEGORIES))

    def data_files(self) -> tuple[Path, Path, Path]:
        return (self.transactions_file, self.categories_file, self.budgets_file)

    def transactions(self) -> Iterator[Transaction]:
        for row in jsonl_rows(self.transactions_file):
            yield Transaction.from_dict(row)

    def categories(self) -> Iterator[str]:
        for row in jsonl_rows(self.categories_file):
            try:
                yield row["name"]
            except KeyError as exc:
                raise BudgetError("카테고리 저장 파일에 name 필드가 없습니다.") from exc

    def budgets(self) -> Iterator[dict[str, Any]]:
        yield from jsonl_rows(self.budgets_file)

    def append_transactions(self, rows: Iterable[Transaction]) -> int:
        """Append transactions one by one to the JSONL file."""
        count = 0
        with self.transactions_file.open("a", encoding="utf-8", newline="\n") as file:
            for transaction in rows:
                file.write(json.dumps(transaction.to_dict(), ensure_ascii=False,
                                      separators=(",", ":")) + "\n")
                count += 1
        return count

    def rewrite_transactions(self, modifier: Callable[[Iterator[Transaction]], Iterable[Transaction]]) -> None:
        write_jsonl(self.transactions_file,
                    (row.to_dict() for row in modifier(self.transactions())))

    def rewrite_categories(self, categories: Iterable[str]) -> None:
        write_jsonl(self.categories_file, ({"name": name} for name in categories))

    def rewrite_budgets(self, rows: Iterable[dict[str, Any]]) -> None:
        write_jsonl(self.budgets_file, rows)
