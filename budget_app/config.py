"""config.py — 기본값과 상수. '바뀔 수 있는 값'을 한곳에 모았다.

파일 이름이나 기본 카테고리를 바꾸고 싶을 때 코드 전체를 뒤지지 않아도 된다.
"""

from __future__ import annotations

from pathlib import Path

# 기본 저장 폴더. --data-dir 옵션으로 바꿀 수 있다.
DEFAULT_DATA_DIR = Path("./data")
DEFAULT_BACKUP_DIR = Path("./backup")

# 저장 파일 이름 (과제 요구: 3개 이상으로 분리)
TRANSACTIONS_FILE = "transactions.jsonl"
CATEGORIES_FILE = "categories.jsonl"
BUDGETS_FILE = "budgets.jsonl"
RECURRING_FILE = "recurring.jsonl"  # 보너스 기능용 4번째 파일
LOG_FILE = "app.log"

# 카테고리 파일이 비어 있을 때 자동으로 넣어줄 기본값
# (과제의 '안 A: 기본 카테고리 자동 생성'을 선택했다. README 에 명시)
DEFAULT_CATEGORIES: tuple[str, ...] = ("food", "transport", "rent", "salary", "etc")

# list 명령의 기본 출력 개수
DEFAULT_LIMIT = 20
# summary 의 카테고리 TOP N 기본값
DEFAULT_TOP = 5

# import/export CSV 스키마 (순서 고정)
CSV_COLUMNS: tuple[str, ...] = ("date", "type", "category", "amount", "memo", "tags")
CSV_REQUIRED: tuple[str, ...] = ("date", "type", "category", "amount")
