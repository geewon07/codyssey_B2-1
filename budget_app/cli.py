"""Argparse CLI and conversational input; delegates all rules to the service."""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, TypeVar

from .formatting import print_transactions
from .repository import BudgetRepository
from .service import BudgetService
from .validators import (
    BudgetError, positive_int, valid_date, valid_tags, valid_type,
)

T = TypeVar("T")


class FriendlyArgumentParser(argparse.ArgumentParser):
    """Expected CLI mistakes become a cause + hint instead of a traceback."""
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"[오류] {message}\n[힌트] 해당 명령에 --help를 붙여 옵션을 확인하세요.\n")


def parser_factory() -> argparse.ArgumentParser:
    parser = FriendlyArgumentParser(
        prog="python -m budget_app",
        description="JSONL 기반 콘솔 가계부 (Python 3.10+, 표준 라이브러리 전용)",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="저장 폴더 (기본값: ./data). 명령 앞에 배치")
    parser.add_argument("--verbose", action="store_true", help="실행 시간/로그 표시")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("add", help="대화형 거래 추가")
    listing = commands.add_parser("list", help="최신 거래 목록")
    listing.add_argument("--limit", type=int, default=20, help="표시할 건수 (기본 20)")

    update = commands.add_parser("update", help="옵션 기반 거래 수정")
    update.add_argument("--id", required=True, help="수정할 거래 ID")
    for name in ("date", "type", "category", "amount", "memo", "tags"):
        update.add_argument(f"--{name}", help=f"변경할 {name}")

    delete = commands.add_parser("delete", help="거래 삭제")
    delete.add_argument("--id", required=True, help="삭제할 거래 ID")

    search = commands.add_parser("search", help="조건 검색 (모든 결과 날짜 최신순)")
    _add_filters(search)

    summary = commands.add_parser("summary", help="월별 수입/지출/예산 요약")
    summary.add_argument("--month", required=True, help="YYYY-MM")
    summary.add_argument("--top", type=int, default=5, help="지출 상위 카테고리 개수 (기본 5)")

    budget = commands.add_parser("budget", help="월 예산 관리")
    budget_actions = budget.add_subparsers(dest="action", required=True)
    set_budget = budget_actions.add_parser("set", help="월 예산 설정/변경")
    set_budget.add_argument("--month", required=True)
    set_budget.add_argument("--amount", required=True)

    category = commands.add_parser("category", help="카테고리 관리")
    category_actions = category.add_subparsers(dest="action", required=True)
    add_cat = category_actions.add_parser("add", help="대화형 카테고리 추가")
    add_cat.add_argument("--name", help="선택: 입력 대신 이름을 옵션으로 지정")
    category_actions.add_parser("list", help="카테고리 조회")
    remove_cat = category_actions.add_parser("remove", help="사용 중이지 않은 카테고리 삭제")
    remove_cat.add_argument("--name", required=True)

    importing = commands.add_parser("import", help="CSV 거래 가져오기 (유효하지 않은 행 건너뜀)")
    importing.add_argument("--from", dest="source", required=True, type=Path,
                           help="CSV 파일 경로")

    exporting = commands.add_parser("export", help="조건에 맞는 거래를 CSV로 내보내기")
    exporting.add_argument("--out", required=True, type=Path, help="출력 파일 경로")
    exporting.add_argument("--month", help="YYYY-MM (또는 --from/--to)")
    exporting.add_argument("--from", dest="start", help="YYYY-MM-DD")
    exporting.add_argument("--to", dest="end", help="YYYY-MM-DD")

    return parser


def _add_filters(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--from", dest="start", help="시작 날짜 YYYY-MM-DD")
    cmd.add_argument("--to", dest="end", help="종료 날짜 YYYY-MM-DD")
    cmd.add_argument("--category", help="카테고리")
    cmd.add_argument("--type", help="income 또는 expense")
    cmd.add_argument("--q", help="메모 부분 문자열 (대소문자 무시)")
    cmd.add_argument("--tag", help="태그 일치")


def prompt(label: str, validator: Callable[[str], T]) -> T:
    """A malformed input gets a hint and another chance; EOF/Ctrl+C ends cleanly."""
    while True:
        value = input(label).strip()
        try:
            return validator(value)
        except BudgetError as exc:
            print(f"[오류] {exc}")
            print("[힌트] 위 안내를 참고해 다시 입력하세요.")


def prompt_transaction(service: BudgetService) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["date"] = prompt("날짜(YYYY-MM-DD): ", valid_date)
    data["type"] = prompt("타입(income/expense): ", valid_type)
    print("등록된 카테고리:", ", ".join(service.categories()))
    data["category"] = prompt("카테고리: ", service.require_category)
    data["amount"] = prompt("금액(양수 정수): ", positive_int)
    data["memo"] = input("메모(선택): ").strip()
    data["tags"] = prompt("태그(쉼표 구분, 없으면 엔터): ", valid_tags)
    return data


def _display_summary(service: BudgetService, month: str, top: int) -> None:
    top = positive_int(top, field="top")
    result = service.summary(month)
    print(f"[{result.month} 월별 요약]")
    if not result.count:
        print("데이터 없음: 해당 월에 거래 내역이 없습니다.")
    print(f"총 수입: {result.income:,}원")
    print(f"총 지출: {result.expense:,}원")
    print(f"잔액: {result.balance:,}원")
    if result.budget is not None:
        usage = (Decimal(result.expense) * 100 / Decimal(result.budget)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP)
        print(f"예산: {result.budget:,}원 (사용률 {usage}%)")
        if result.expense > result.budget:
            print(f"[경고] 월 예산을 {result.expense - result.budget:,}원 초과했습니다!")
    print(f"\n지출 TOP {top}")
    category_ranking = sorted(result.by_category.items(),
                              key=lambda kv: (-kv[1], kv[0]))[:top]
    if not category_ranking:
        print("지출 데이터 없음")
    for index, (category, amount) in enumerate(category_ranking, 1):
        print(f"{index}) {category}: {amount:,}원")


def dispatch(args: argparse.Namespace, service: BudgetService) -> None:
    if args.command == "add":
        transaction = service.add(**prompt_transaction(service))
        print(f"[저장 완료] id={transaction.id}")
    elif args.command == "list":
        print_transactions(service.list_latest(args.limit))
    elif args.command == "update":
        changes = {k: getattr(args, k) for k in
                   ("date", "type", "category", "amount", "memo", "tags")
                   if getattr(args, k) is not None}
        transaction = service.update(args.id, changes)
        print(f"[수정 완료] id={transaction.id}")
    elif args.command == "delete":
        service.delete(args.id)
        print(f"[삭제 완료] id={args.id}")
    elif args.command == "search":
        print_transactions(service.search(start=args.start, end=args.end,
                                          category=args.category, type=args.type,
                                          q=args.q, tag=args.tag))
    elif args.command == "summary":
        _display_summary(service, args.month, args.top)
    elif args.command == "budget":
        amount = service.set_budget(args.month, args.amount)
        print(f"[저장 완료] {args.month} 예산 {amount:,}원")
    elif args.command == "category":
        if args.action == "list":
            for name in service.categories():
                print(f"- {name}")
        elif args.action == "add":
            name = args.name if args.name is not None else input("카테고리명: ")
            print(f"[저장 완료] category={service.add_category(name)}")
        elif args.action == "remove":
            service.remove_category(args.name)
            print(f"[삭제 완료] category={args.name}")
    elif args.command == "import":
        result = service.import_csv(args.source)
        print(f"[완료] imported={result.imported}, skipped={result.skipped}")
        for warning in result.examples:
            print(f"[건너뜀] {warning}")
    elif args.command == "export":
        count = service.export_csv(args.out, month=args.month,
                                   start=args.start, end=args.end)
        print(f"[완료] {args.out} ({count} records)")


def main(argv: list[str] | None = None) -> int:
    args = parser_factory().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="[로그] %(message)s", stream=sys.stderr)
    try:
        service = BudgetService(BudgetRepository(args.data_dir))
        dispatch(args, service)
        return 0
    except (BudgetError, OSError, UnicodeError, ValueError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        print("[힌트] 입력 값·파일 경로·접근 권한을 확인하고 --help를 참고하세요.",
              file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\n[오류] 입력이 중단되었습니다. 다시 실행하세요.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Never print a traceback in the CLI, including unexpected failures.
        print(f"[오류] 처리 중 문제가 발생했습니다: {exc}", file=sys.stderr)
        print("[힌트] data 폴더의 파일을 확인하고 명령을 다시 실행하세요.", file=sys.stderr)
        return 1
