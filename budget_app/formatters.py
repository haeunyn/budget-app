"""formatters.py — 출력 모양 담당. (보너스 3: 외부 라이브러리 없이 테이블 정렬)

■ 왜 출력을 따로 뺐나?
  - 서비스는 '계산 결과 객체'를 주고, CLI 는 그걸 '어떻게 보여줄지' 정한다.
  - 출력 코드가 서비스에 섞이면, 나중에 JSON 출력을 추가할 때 계산 로직을 건드려야 한다.
  - 여기만 고치면 표 모양이 전부 바뀐다.

■ 한글 폭 문제
  터미널에서 한글 한 글자는 영문 두 글자만큼의 자리를 차지한다.
  파이썬의 len('점심') 은 2 지만 화면에서는 4칸이다. 그래서 그냥 ljust 를 쓰면
  한글이 섞인 표는 오른쪽 끝이 들쭉날쭉해진다.
  unicodedata.east_asian_width 로 '넓은 글자'를 판별해 폭을 직접 계산한다.
"""

from __future__ import annotations

import unicodedata
from typing import Sequence

from .models import MonthlySummary, RecurringRule, Transaction


def display_width(text: str) -> int:
    """터미널에서 차지하는 실제 칸 수를 센다. 한글/한자/일본어는 2칸."""
    width = 0
    for ch in text:
        # 'W' = Wide(한자/가나), 'F' = Fullwidth(전각) → 2칸
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad(text: str, target: int, align: str = "left") -> str:
    """실제 표시 폭 기준으로 빈칸을 채운다."""
    gap = max(0, target - display_width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    aligns: Sequence[str] | None = None,
) -> str:
    """간단한 텍스트 표를 만든다.

    각 열의 폭은 '그 열에서 가장 긴 값'에 맞춘다.
    데이터가 없으면 빈 문자열을 돌려주고, 호출한 쪽이 '데이터 없음'을 출력한다.
    """
    if not rows:
        return ""
    aligns = aligns or ["left"] * len(headers)
    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))

    lines = []
    lines.append("  ".join(pad(h, widths[i], aligns[i]) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def won(amount: int) -> str:
    """12345 -> '12,345원'. 천 단위 구분으로 금액을 읽기 쉽게 만든다."""
    return f"{amount:,}원"


def format_transactions(rows: Sequence[Transaction]) -> str:
    """거래 목록을 표로."""
    table = render_table(
        headers=["ID", "날짜", "타입", "카테고리", "금액", "메모", "태그"],
        rows=[
            [
                tx.id,
                tx.date,
                "수입" if tx.type == "income" else "지출",
                tx.category,
                f"{tx.amount:,}",
                tx.memo,
                ",".join(tx.tags),
            ]
            for tx in rows
        ],
        aligns=["left", "left", "left", "left", "right", "left", "left"],
    )
    return table


def format_transaction_line(tx: Transaction) -> str:
    """한 건을 한 줄로. add/update/delete 결과 확인용."""
    memo = f" | {tx.memo}" if tx.memo else ""
    tags = f" | #{' #'.join(tx.tags)}" if tx.tags else ""
    kind = "수입" if tx.type == "income" else "지출"
    return f"{tx.id} | {tx.date} | {kind} | {tx.category} | {tx.amount:,}원{memo}{tags}"


def format_summary(summary: MonthlySummary) -> str:
    """월별 요약 화면을 만든다."""
    lines: list[str] = []
    lines.append(f"[{summary.month}] 월별 요약  (거래 {summary.transaction_count}건)")
    lines.append("")
    lines.append(f"총 수입: {won(summary.total_income)}")
    lines.append(f"총 지출: {won(summary.total_expense)}")
    lines.append(f"잔액   : {won(summary.balance)}")

    if summary.budget is not None:
        rate = summary.usage_rate
        lines.append("")
        lines.append(f"예산   : {won(summary.budget)} (사용률 {rate}%)")
        if summary.is_over_budget:
            over = summary.total_expense - summary.budget
            lines.append(f"⚠️  예산을 {won(over)} 초과했습니다!")
        elif rate is not None and rate >= 80:
            left = summary.budget - summary.total_expense
            lines.append(f"주의: 예산의 {rate}% 를 썼습니다. (남은 금액 {won(left)})")
    else:
        lines.append("")
        lines.append(f"예산   : 설정되지 않음  (budget set --month {summary.month} --amount <금액>)")

    if summary.top_expenses:
        lines.append("")
        lines.append(f"지출 TOP {len(summary.top_expenses)}")
        ranked_rows = [
            [f"{i})", name, f"{amount:,}원"]
            for i, (name, amount) in enumerate(summary.top_expenses, start=1)
        ]
        lines.append(render_table(["", "카테고리", "합계"], ranked_rows, ["left", "left", "right"]))
    return "\n".join(lines)


def format_recurring(rules: Sequence[RecurringRule]) -> str:
    return render_table(
        headers=["ID", "타입", "매달", "카테고리", "금액", "메모"],
        rows=[
            [
                r.id,
                "수입" if r.type == "income" else "지출",
                f"{r.day}일",
                r.category,
                f"{r.amount:,}",
                r.memo,
            ]
            for r in rules
        ],
        aligns=["left", "left", "right", "left", "right", "left"],
    )
