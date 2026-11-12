"""Run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from budget_app.cli import main
from budget_app.models import Transaction
from budget_app.repository import BudgetRepository
from budget_app.service import BudgetService, latest_stream
from budget_app.validators import BudgetError, positive_int, valid_date


class BudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = BudgetRepository(self.base / "data")
        self.svc = BudgetService(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create(self, date: str = "2026-11-12", category: str = "food",
               type: str = "expense", amount: int = 100, memo: str = "테스트",
               tags: str = "x,y") -> Transaction:
        return self.svc.add(date=date, category=category, type=type,
                            amount=amount, memo=memo, tags=tags)

    def test_init_creates_all_files_and_default_categories(self) -> None:
        self.assertEqual(len(self.repo.data_files()), 3)
        self.assertTrue(all(p.exists() for p in self.repo.data_files()))
        self.assertIn("food", self.svc.categories())
        self.assertIn("salary", self.svc.categories())

    def test_crud_persists_and_id_is_unique(self) -> None:
        first = self.create()
        second = self.create(date="2026-11-10")
        self.assertNotEqual(first.id, second.id)
        new_svc = BudgetService(BudgetRepository(self.repo.data_dir))
        self.assertEqual(new_svc.get(first.id).memo, "테스트")
        modified = new_svc.update(first.id, {"amount": "2400", "memo": "수정", "tags": "a,b"})
        self.assertEqual(modified.amount, 2400)
        self.assertEqual(new_svc.get(first.id).memo, "수정")
        new_svc.delete(first.id)
        self.assertIsNone(new_svc.get(first.id))
        self.assertEqual(new_svc.get(second.id).amount, 100)

    def test_delete_missing_and_update_no_changes_raise(self) -> None:
        with self.assertRaisesRegex(BudgetError, "없는 데이터"):
            self.svc.delete("TX-MISSING")
        first = self.create()
        with self.assertRaisesRegex(BudgetError, "변경할"):
            self.svc.update(first.id, {})
        with self.assertRaises(BudgetError):
            self.svc.update(first.id, {"amount": 0})
        self.assertEqual(self.svc.get(first.id).amount, 100)

    def test_invalid_input_and_category(self) -> None:
        with self.assertRaises(BudgetError):
            valid_date("2026-02-30")
        for amount in ("0", "-1", "10.5", "abc", True):
            with self.subTest(amount=amount), self.assertRaises(BudgetError):
                positive_int(amount)
        with self.assertRaises(BudgetError):
            self.svc.add(date="2026-11-12", type="wrong", category="food", amount=3)
        with self.assertRaises(BudgetError):
            self.svc.add(date="2026-11-12", type="expense", category="missing", amount=3)

    def test_latest_list_and_search_multistage_merge(self) -> None:
        for i in range(1, 11):
            self.create(date=f"2026-11-{i:02}", memo="match" if i % 2 else "no",
                        tags="even" if i % 2 == 0 else "odd")
        records = self.svc.list_latest(3)
        self.assertEqual([r.date for r in records],
                         ["2026-11-10", "2026-11-09", "2026-11-08"])
        searched = list(self.svc.search(start="2026-11-03", end="2026-11-09", q="MATCH", tag="odd"))
        self.assertEqual([r.date for r in searched],
                         ["2026-11-09", "2026-11-07", "2026-11-05", "2026-11-03"])
        # Deliberately tiny chunks and fan-in to exercise all merge stages.
        merged = list(latest_stream(self.repo.transactions(), chunk_size=2, fan_in=2))
        self.assertEqual([r.date for r in merged],
                         [f"2026-11-{i:02}" for i in range(10, 0, -1)])

    def test_summary_budget_and_warning_data(self) -> None:
        self.create(type="income", category="salary", amount=2000)
        self.create(amount=600)
        self.create(amount=200, date="2026-11-03", category="transport")
        self.create(amount=9999, date="2026-10-20")
        self.svc.set_budget("2026-11", 700)
        summary = self.svc.summary("2026-11")
        self.assertEqual((summary.income, summary.expense, summary.balance), (2000, 800, 1200))
        self.assertEqual(summary.budget, 700)
        self.assertEqual(summary.by_category["food"], 600)
        self.assertEqual(self.svc.summary("2026-09").count, 0)
        self.assertEqual(BudgetService(BudgetRepository(self.repo.data_dir)).summary("2026-11").budget, 700)

    def test_category_cannot_remove_if_referenced(self) -> None:
        self.create()
        with self.assertRaisesRegex(BudgetError, "사용한 거래"):
            self.svc.remove_category("food")
        self.assertEqual(self.svc.add_category("books"), "books")
        self.svc.remove_category("books")
        self.assertNotIn("books", self.svc.categories())
        with self.assertRaises(BudgetError):
            self.svc.add_category("food")

    def test_import_export_utf8_csv_and_bad_rows(self) -> None:
        source = self.base / "source.csv"
        with source.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "type", "category", "amount", "memo", "tags"])
            w.writerow(["2026-11-10", "expense", "food", "100", "점심", "meal,work"])
            w.writerow(["2026-11-12", "income", "salary", "300", "월급", ""])
            w.writerow(["2026-13-10", "expense", "food", "100", "오류", ""])
            w.writerow(["2026-11-13", "expense", "unregistered", "100", "오류", ""])
        outcome = self.svc.import_csv(source)
        self.assertEqual((outcome.imported, outcome.skipped), (2, 2))
        target = self.base / "out.csv"
        self.assertEqual(self.svc.export_csv(target, month="2026-11"), 2)
        with target.open(encoding="utf-8", newline="") as f:
            content = list(csv.DictReader(f))
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0]["tags"], "meal,work")
        self.assertEqual(content[0]["memo"], "점심")
        self.assertEqual(set(content[0].keys()),
                         {"date", "type", "category", "amount", "memo", "tags"})
        with self.assertRaises(BudgetError):
            self.svc.export_csv(self.base / "wrong.csv")
        self.assertFalse((self.base / "wrong.csv").exists())

    def test_import_invalid_header_does_not_mutate(self) -> None:
        self.create()
        source = self.base / "malformed.csv"
        source.write_text("wrong,headers\na,b\n", encoding="utf-8")
        original = self.repo.transactions_file.read_bytes()
        with self.assertRaises(BudgetError):
            self.svc.import_csv(source)
        self.assertEqual(self.repo.transactions_file.read_bytes(), original)

    def test_exact_three_files_and_plain_output(self) -> None:
        self.create()
        self.assertEqual({p.name for p in self.repo.data_files()},
                         {"transactions.jsonl", "categories.jsonl", "budgets.jsonl"})
        self.assertEqual({p.name for p in self.repo.data_dir.iterdir()},
                         {"transactions.jsonl", "categories.jsonl", "budgets.jsonl"})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            from budget_app.formatting import print_transactions
            self.assertEqual(print_transactions(self.svc.list_latest()), 1)
        self.assertIn(" | expense | food | 100 | ", output.getvalue())

    def test_cli_help_only_lists_required_commands(self) -> None:
        from budget_app.cli import parser_factory
        parser = parser_factory()
        available = next(a.choices for a in parser._actions if hasattr(a, "choices") and isinstance(a.choices, dict))
        self.assertEqual(set(available), {"add", "list", "update", "delete", "search",
                                          "summary", "budget", "category", "import", "export"})

    def test_cli_interactive_and_exit_code_without_traceback(self) -> None:
        stdout = io.StringIO()
        with patch("builtins.input", side_effect=["bad", "2026-11-12", "expense", "food", "1200", "간식", "snack"]):
            with contextlib.redirect_stdout(stdout):
                status = main(["--data-dir", str(self.repo.data_dir), "add"])
        self.assertEqual(status, 0)
        self.assertIn("[오류]", stdout.getvalue())
        self.assertIn("[저장 완료]", stdout.getvalue())

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status = main(["--data-dir", str(self.repo.data_dir), "delete", "--id", "TX-NOTFOUND"])
        self.assertNotEqual(status, 0)
        self.assertIn("[힌트]", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
