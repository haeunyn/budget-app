"""models.py — 데이터의 '모양'을 정의하는 계층.

■ 왜 dataclass 인가?
  - 딕셔너리로 데이터를 들고 다니면 `tx["amout"]` 같은 오타를 실행 전까지 못 잡는다.
  - dataclass 는 필드 이름과 타입이 고정되므로, 오타는 편집기에서 바로 빨간 줄이 뜬다.
  - __init__, __repr__, __eq__ 를 자동으로 만들어 주므로 보일러플레이트가 없다.

■ 왜 to_dict / from_dict 를 모델이 갖고 있나?
  - "파이썬 객체 ↔ 저장용 딕셔너리" 변환 규칙은 데이터의 모양과 한 몸이다.
  - 이걸 저장소에 두면, 필드를 하나 추가할 때 두 파일을 고쳐야 한다.

■ from __future__ import annotations 가 맨 위에 있는 이유
  - 타입 힌트를 '문자열'로 미뤄서 평가한다.
  - 덕분에 `list[str]`, `str | None` 같은 최신 문법을 파이썬 3.9에서도 쓸 수 있고,
    3.10 이상에서도 똑같이 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Literal 은 "이 값만 허용한다"는 계약을 타입으로 표현한다.
# TxType 이라는 이름을 쓰면, 함수 시그니처만 봐도 income/expense 둘뿐임을 알 수 있다.
TxType = Literal["income", "expense"]


@dataclass
class Transaction:
    """거래 내역 한 건.

    id       : TX-000001 형식의 유일한 식별자
    type     : income(수입) 또는 expense(지출)
    date     : YYYY-MM-DD
    amount   : 양의 정수(원). 소수점을 쓰지 않는 이유는 아래 주석 참고
    category : 등록된 카테고리 이름
    memo     : 선택
    tags     : 선택, 문자열 목록
    """

    id: str
    type: TxType
    date: str
    amount: int
    category: str
    memo: str = ""
    # 가변 기본값(list)은 default_factory 로 줘야 한다.
    # `tags: list[str] = []` 로 쓰면 모든 인스턴스가 같은 리스트를 공유하는 고전적 버그가 생긴다.
    tags: list[str] = field(default_factory=list)

    # amount 를 int 로 고정한 이유:
    # 돈을 float 로 다루면 0.1 + 0.2 != 0.3 같은 부동소수점 오차가 쌓인다.
    # 원화는 소수점이 없으므로 정수(원 단위)로 저장하는 것이 가장 안전하다.

    @property
    def month(self) -> str:
        """'2026-09-13' -> '2026-09'. 월별 요약에서 사용한다."""
        return self.date[:7]

    @property
    def signed_amount(self) -> int:
        """수입은 +, 지출은 -. 잔액 계산을 한 줄로 만들기 위한 도우미."""
        return self.amount if self.type == "income" else -self.amount

    def to_dict(self) -> dict[str, Any]:
        """JSONL 한 줄로 저장할 딕셔너리."""
        return {
            "id": self.id,
            "type": self.type,
            "date": self.date,
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Transaction:
        """저장된 딕셔너리에서 객체를 복원한다.

        .get() 으로 기본값을 주는 이유: 예전에 저장한 줄에 memo/tags 가 없을 수 있다.
        파일 기반 저장은 '스키마 변경'을 이렇게 흡수해야 한다.
        """
        return cls(
            id=str(raw["id"]),
            type=raw["type"],
            date=str(raw["date"]),
            amount=int(raw["amount"]),
            category=str(raw["category"]),
            memo=str(raw.get("memo", "")),
            tags=list(raw.get("tags", [])),
        )


@dataclass
class Category:
    """카테고리 한 건. 지금은 이름뿐이지만, 나중에 색/아이콘이 붙을 자리다."""

    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Category:
        return cls(name=str(raw["name"]))


@dataclass
class Budget:
    """월 예산 한 건. month 는 'YYYY-MM'."""

    month: str
    amount: int

    def to_dict(self) -> dict[str, Any]:
        return {"month": self.month, "amount": self.amount}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Budget:
        return cls(month=str(raw["month"]), amount=int(raw["amount"]))


@dataclass
class RecurringRule:
    """(보너스) 반복 내역 규칙. 월급/월세처럼 매달 같은 날 생기는 거래."""

    id: str
    type: TxType
    day: int  # 1~31, 매달 며칠에 생기는지
    amount: int
    category: str
    memo: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "day": self.day,
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RecurringRule:
        return cls(
            id=str(raw["id"]),
            type=raw["type"],
            day=int(raw["day"]),
            amount=int(raw["amount"]),
            category=str(raw["category"]),
            memo=str(raw.get("memo", "")),
            tags=list(raw.get("tags", [])),
        )


@dataclass
class MonthlySummary:
    """summary 명령의 결과를 담는 그릇.

    서비스 계층이 이 객체를 돌려주고, CLI 계층이 이걸 '보기 좋게' 출력한다.
    계산과 출력을 분리하기 위한 경계선이다.
    """

    month: str
    total_income: int
    total_expense: int
    top_expenses: list[tuple[str, int]]  # [(카테고리, 합계), ...] 내림차순
    budget: int | None = None
    transaction_count: int = 0

    @property
    def balance(self) -> int:
        return self.total_income - self.total_expense

    @property
    def usage_rate(self) -> float | None:
        """예산 대비 지출 사용률(%). 예산이 없으면 None."""
        if not self.budget:
            return None
        return round(self.total_expense / self.budget * 100, 1)

    @property
    def is_over_budget(self) -> bool:
        return self.budget is not None and self.total_expense > self.budget
