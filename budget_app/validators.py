"""Input validation: a bad user value raises a friendly domain error."""
from __future__ import annotations

import re
from datetime import date


class BudgetError(Exception):
    """An expected error that should be shown to users without a traceback."""


def valid_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BudgetError("날짜는 YYYY-MM-DD 형식이어야 합니다. 예: 2026-11-12")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise BudgetError("실제로 존재하는 날짜를 입력하세요. 예: 2026-11-12") from exc
    return value


def valid_month(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise BudgetError("월은 YYYY-MM 형식이어야 합니다. 예: 2026-11")
    try:
        date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise BudgetError("실제로 존재하는 월을 입력하세요. 예: 2026-11") from exc
    return value


def positive_int(value: object, *, field: str = "금액") -> int:
    if isinstance(value, bool):
        raise BudgetError(f"{field}은(는) 1 이상의 정수여야 합니다.")
    try:
        if isinstance(value, float) or not re.fullmatch(r"\+?\d+", str(value).strip()):
            raise ValueError
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BudgetError(f"{field}은(는) 1 이상의 정수여야 합니다.") from exc
    if number <= 0:
        raise BudgetError(f"{field}은(는) 1 이상의 정수여야 합니다.")
    return number


def valid_type(value: str) -> str:
    if value not in ("income", "expense"):
        raise BudgetError("타입은 income 또는 expense만 가능합니다.")
    return value


def valid_category(value: str) -> str:
    if not isinstance(value, str):
        raise BudgetError("카테고리 이름은 문자열이어야 합니다.")
    name = value.strip().lower()
    if not name or len(name) > 60 or any(c in name for c in "\r\n\t"):
        raise BudgetError("카테고리는 1~60자의 한 줄 이름으로 입력하세요.")
    return name


def valid_tags(value: object) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list) and all(isinstance(v, str) for v in value):
        values = value
    else:
        raise BudgetError("태그는 쉼표로 구분한 문자열이어야 합니다.")
    result = list(dict.fromkeys(v.strip() for v in values if v.strip()))
    if any(len(tag) > 60 for tag in result):
        raise BudgetError("태그 하나는 60자 이하여야 합니다.")
    return result
