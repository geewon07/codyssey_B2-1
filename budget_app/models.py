"""Transaction domain model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .validators import BudgetError, positive_int, valid_category, valid_date, valid_tags, valid_type


@dataclass(frozen=True)
class Transaction:
    id: str
    type: str
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.startswith("TX-"):
            raise BudgetError("거래 ID가 잘못되었습니다.")
        valid_type(self.type)
        valid_date(self.date)
        if type(self.amount) is not int:
            raise BudgetError("금액은 정수여야 합니다.")
        positive_int(self.amount)
        if valid_category(self.category) != self.category:
            raise BudgetError("카테고리 저장 값이 올바르지 않습니다.")
        if not isinstance(self.memo, str):
            raise BudgetError("메모는 문자열이어야 합니다.")
        valid_tags(self.tags)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Transaction":
        try:
            return cls(id=raw["id"], type=raw["type"], date=raw["date"],
                       amount=raw["amount"], category=raw["category"],
                       memo=raw.get("memo", ""), tags=raw.get("tags", []))
        except (KeyError, TypeError) as exc:
            raise BudgetError(f"거래 저장 데이터에 필수 필드가 없습니다: {exc}") from exc
