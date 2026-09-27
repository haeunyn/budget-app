"""validators.py — 입력값 검증만 모아둔 곳.

■ 왜 따로 뺐나?
  - 같은 검증(날짜 형식 등)이 add(대화형), import(CSV), update(옵션) 세 군데에서 필요하다.
  - 한 곳에 모아두면 규칙이 바뀔 때 한 번만 고치면 된다.
  - 검증 함수는 "통과하면 정리된 값을 돌려주고, 아니면 ValidationError 를 던진다"로 통일했다.
    이렇게 하면 호출하는 쪽 코드가 if 문 없이 깔끔해진다.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .errors import ValidationError
from .models import TxType

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
VALID_TYPES: tuple[str, ...] = ("income", "expense")


def validate_date(value: str) -> str:
    """'2026-09-13' 처럼 실제로 존재하는 날짜인지 확인하고 그대로 돌려준다.

    정규식만으로는 2024-13-40 을 걸러낼 수 없다(형식은 맞다).
    그래서 strptime 으로 실제 달력에 있는 날짜인지까지 확인한다.
    """
    value = value.strip()
    if not DATE_PATTERN.match(value):
        raise ValidationError(
            "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).",
            f"예: {date.today().isoformat()}",
        )
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(
            f"존재하지 않는 날짜입니다: {value}",
            "월은 01~12, 일은 그 달의 마지막 날까지만 가능합니다.",
        ) from None
    return value


def validate_month(value: str) -> str:
    """'2026-09' 형식의 월 문자열을 확인한다."""
    value = value.strip()
    if not MONTH_PATTERN.match(value):
        raise ValidationError(
            "월 형식이 올바르지 않습니다 (YYYY-MM).",
            f"예: {date.today().strftime('%Y-%m')}",
        )
    month_part = int(value[5:7])
    if not 1 <= month_part <= 12:
        raise ValidationError(f"존재하지 않는 월입니다: {value}", "월은 01~12 사이여야 합니다.")
    return value


def validate_amount(value: str | int) -> int:
    """금액을 양의 정수로 변환한다. 0과 음수는 거부한다.

    '15,000' 처럼 쉼표가 들어와도 받아준다. 사용자가 실제로 그렇게 입력하기 때문이다.
    """
    raw = str(value).strip().replace(",", "").replace("원", "")
    if not raw:
        raise ValidationError("금액이 비어 있습니다.", "예: 15000")
    try:
        amount = int(raw)
    except ValueError:
        raise ValidationError(
            f"금액은 숫자여야 합니다: {value}",
            "쉼표는 써도 됩니다. 예: 15000 또는 15,000",
        ) from None
    if amount <= 0:
        raise ValidationError(
            f"금액은 0보다 큰 값이어야 합니다: {amount}",
            "지출도 양수로 입력합니다. 수입/지출 구분은 type 이 합니다.",
        )
    return amount


def validate_type(value: str) -> TxType:
    """income / expense 만 허용한다."""
    normalized = value.strip().lower()
    if normalized not in VALID_TYPES:
        raise ValidationError(
            f"타입은 income 또는 expense 여야 합니다: {value}",
            "income = 수입, expense = 지출",
        )
    return normalized  # type: ignore[return-value]


def validate_day(value: str | int) -> int:
    """(보너스) 반복 내역의 '매달 며칠'. 1~31."""
    try:
        day = int(str(value).strip())
    except ValueError:
        raise ValidationError(f"일자는 숫자여야 합니다: {value}", "1~31 사이의 숫자") from None
    if not 1 <= day <= 31:
        raise ValidationError(f"일자는 1~31 사이여야 합니다: {day}", "예: 25 (매달 25일)")
    return day


def parse_tags(value: str) -> list[str]:
    """'meal, 점심 ,,' -> ['meal', '점심']

    쉼표로 나누고, 공백을 정리하고, 빈 조각은 버린다.
    사용자가 어떻게 입력하든 저장되는 모양은 하나로 통일된다.
    """
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def validate_date_range(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """기간 옵션(--from/--to)을 검증한다. 시작일이 종료일보다 늦으면 오류."""
    start = validate_date(date_from) if date_from else None
    end = validate_date(date_to) if date_to else None
    if start and end and start > end:
        raise ValidationError(
            f"시작일이 종료일보다 늦습니다: {start} > {end}",
            "--from 에는 더 이른 날짜를 넣어주세요.",
        )
    return start, end
