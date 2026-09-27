"""services.py — 서비스 계층. '업무 규칙'을 담당한다.

■ 이 계층이 답하는 질문들
  - 카테고리가 등록되어 있지 않으면 거래를 추가해도 되는가? (안 된다)
  - 사용 중인 카테고리를 지워도 되는가? (대체 카테고리가 없으면 안 된다)
  - 이번 달 예산 대비 얼마나 썼는가?

■ 이 계층이 하지 않는 일
  - 화면에 예쁘게 출력하기 (CLI 계층의 일)
  - 파일을 직접 열기 (저장소 계층의 일)
  서비스는 저장소에게 "거래를 하나씩 달라"고 하고, 규칙에 따라 판단한 결과를
  CLI 에게 **객체로** 돌려준다. print 가 이 파일에 하나도 없는 것이 그 증거다.

■ 왜 이렇게 나누나?
  나중에 이 프로그램을 웹 API 로 바꾼다고 해보자. CLI 계층만 새로 쓰면 되고
  services.py 와 repository.py 는 그대로 쓸 수 있다. 규칙이 화면에 묶여 있지 않기 때문이다.
"""

from __future__ import annotations

import csv
import heapq
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from . import config
from .errors import ConflictError, NotFoundError, StorageError, ValidationError
from .models import Budget, Category, MonthlySummary, RecurringRule, Transaction, TxType
from .repository import (
    BudgetStore,
    CategoryStore,
    RecurringStore,
    TransactionRepository,
)
from .validators import (
    parse_tags,
    validate_amount,
    validate_date,
    validate_day,
    validate_month,
    validate_type,
)


@dataclass
class SearchFilter:
    """검색 조건을 담는 그릇.

    인자를 6개씩 늘어놓는 대신 객체 하나로 묶으면
    함수 시그니처가 짧아지고, 조건이 하나 늘어도 호출부를 고치지 않아도 된다.
    """

    date_from: str | None = None
    date_to: str | None = None
    category: str | None = None
    tx_type: TxType | None = None
    keyword: str | None = None
    tag: str | None = None
    month: str | None = None

    def matches(self, tx: Transaction) -> bool:
        """거래 한 건이 이 조건을 모두 만족하는지 판단한다.

        조건이 None 이면 '그 조건은 보지 않는다'는 뜻이다.
        """
        if self.month and tx.month != self.month:
            return False
        if self.date_from and tx.date < self.date_from:
            return False
        if self.date_to and tx.date > self.date_to:
            return False
        if self.category and tx.category != self.category:
            return False
        if self.tx_type and tx.type != self.tx_type:
            return False
        if self.keyword and self.keyword.lower() not in tx.memo.lower():
            return False
        if self.tag and self.tag not in tx.tags:
            return False
        return True


class CategoryService:
    """카테고리 규칙 담당."""

    def __init__(self, store: CategoryStore, tx_repo: TransactionRepository) -> None:
        self.store = store
        self.tx_repo = tx_repo

    def bootstrap(self) -> list[str]:
        """카테고리 파일이 비어 있으면 기본 카테고리를 만들어 준다.

        과제에서 제시한 '안 A(기본 카테고리 자동 생성)'를 선택했다.
        이유: 첫 실행에서 add 가 막히면 사용자가 뭘 해야 할지 모른다.
        바로 쓸 수 있게 해주고, 필요하면 지우게 하는 편이 낫다고 판단했다.
        """
        self.store.ensure_file()
        if self.store.names():
            return []
        created = list(config.DEFAULT_CATEGORIES)
        self.store.rewrite([Category(name=name) for name in created])
        return created

    def list(self) -> list[str]:
        return sorted(self.store.names())

    def add(self, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValidationError("카테고리 이름이 비어 있습니다.", "예: food")
        if " " in name:
            raise ValidationError(
                f"카테고리 이름에 공백을 쓸 수 없습니다: '{name}'",
                "하이픈이나 밑줄을 쓰세요. 예: side-income",
            )
        if self.store.exists(name):
            raise ConflictError(
                f"이미 있는 카테고리입니다: {name}",
                "category list 로 현재 목록을 확인하세요.",
            )
        self.store.append(Category(name=name))
        return name

    def usage_count(self, name: str) -> int:
        """해당 카테고리를 쓰는 거래가 몇 건인지 센다(스트리밍)."""
        return sum(1 for tx in self.tx_repo.stream() if tx.category == name)

    def remove(self, name: str, replace_with: str | None = None) -> tuple[str, int]:
        """카테고리를 지운다. 사용 중이면 대체 카테고리를 요구한다.

        과제 요구: "삭제를 막거나 / 대체 카테고리를 요구해야 한다" → 둘 다 구현했다.
        --replace-with 가 없으면 막고, 있으면 기존 거래를 그 카테고리로 옮긴 뒤 지운다.
        """
        if not self.store.exists(name):
            raise NotFoundError(
                f"없는 카테고리입니다: {name}",
                "category list 로 현재 목록을 확인하세요.",
            )
        used = self.usage_count(name)
        moved = 0
        if used:
            if not replace_with:
                raise ConflictError(
                    f"'{name}' 카테고리를 쓰는 거래가 {used}건 있어 삭제할 수 없습니다.",
                    f"--replace-with <다른카테고리> 를 주면 {used}건을 옮기고 삭제합니다.",
                )
            if replace_with == name:
                raise ValidationError(
                    "대체 카테고리가 삭제할 카테고리와 같습니다.",
                    "다른 카테고리 이름을 지정하세요.",
                )
            if not self.store.exists(replace_with):
                raise NotFoundError(
                    f"대체 카테고리가 없습니다: {replace_with}",
                    "먼저 category add 로 만들어 주세요.",
                )

            def replaced() -> Iterator[Transaction]:
                """거래를 하나씩 읽으며 카테고리만 바꿔 흘려보낸다(스트리밍 재작성)."""
                for tx in self.tx_repo.stream():
                    if tx.category == name:
                        tx.category = replace_with  # type: ignore[assignment]
                    yield tx

            self.tx_repo.rewrite(replaced())
            moved = used

        remaining = [c for c in self.store.read_all() if c.name != name]
        self.store.rewrite(remaining)
        return name, moved

    def ensure_exists(self, name: str) -> str:
        """거래 추가/수정 시 카테고리가 등록되어 있는지 확인한다."""
        name = name.strip()
        if not self.store.exists(name):
            available = ", ".join(self.list()) or "(없음)"
            raise NotFoundError(
                f"등록되지 않은 카테고리입니다: {name}",
                f"사용 가능: {available} / 새로 만들려면: category add --name {name}",
            )
        return name


class TransactionService:
    """거래 내역 규칙 담당. 이 프로그램의 핵심 서비스."""

    def __init__(self, repo: TransactionRepository, categories: CategoryService) -> None:
        self.repo = repo
        self.categories = categories

    # ---------- 생성 ----------

    def add(
        self,
        *,
        date: str,
        tx_type: str,
        category: str,
        amount: str | int,
        memo: str = "",
        tags: str | list[str] = "",
    ) -> Transaction:
        """검증 -> id 생성 -> 한 줄 덧붙이기.

        검증을 먼저 전부 통과시킨 뒤에 파일에 쓴다.
        중간에 실패해서 '반쯤 저장된 상태'가 생기지 않게 하기 위해서다.
        """
        clean_date = validate_date(date)
        clean_type = validate_type(tx_type)
        clean_amount = validate_amount(amount)
        clean_category = self.categories.ensure_exists(category)
        clean_tags = tags if isinstance(tags, list) else parse_tags(tags)

        tx = Transaction(
            id=self.repo.next_id(),
            type=clean_type,
            date=clean_date,
            amount=clean_amount,
            category=clean_category,
            memo=memo.strip(),
            tags=clean_tags,
        )
        self.repo.append(tx)
        return tx

    # ---------- 조회 ----------

    def stream(self, flt: SearchFilter | None = None) -> Iterator[Transaction]:
        """조건에 맞는 거래를 하나씩 내보낸다. ★ 제너레이터 체인

        repo.stream() 이 한 줄씩 주고, 여기서 조건에 맞는 것만 통과시킨다.
        리스트를 만들지 않으므로 이 단계에서도 메모리는 늘지 않는다.
        """
        source = self.repo.stream()
        if flt is None:
            yield from source
            return
        for tx in source:
            if flt.matches(tx):
                yield tx

    def latest(self, limit: int, flt: SearchFilter | None = None) -> list[Transaction]:
        """최신순 상위 N건. ★ 이 프로그램에서 가장 설명할 거리가 많은 함수

        문제: "최신순"이려면 정렬이 필요한데, 정렬하려면 전부 모아야 하는 것 아닌가?
        해결: heapq.nlargest 는 스트림을 한 건씩 받으면서 **크기 N짜리 힙만** 유지한다.
              10만 건을 읽어도 메모리에 동시에 존재하는 것은 N건뿐이다.

        정렬 기준이 (date, id) 인 이유:
          - 같은 날짜가 여러 건이면 순서가 들쭉날쭉해진다.
          - id 는 등록 순서대로 증가하므로, 같은 날짜 안에서는 나중에 넣은 것이 위로 온다.
          - 둘 다 자리수가 고정된 문자열이라 문자열 비교만으로 올바르게 정렬된다.
        """
        if limit <= 0:
            raise ValidationError("--limit 은 1 이상이어야 합니다.", "예: --limit 10")
        return heapq.nlargest(limit, self.stream(flt), key=lambda tx: (tx.date, tx.id))

    def get(self, tx_id: str) -> Transaction:
        tx = self.repo.find_by_id(tx_id)
        if tx is None:
            raise NotFoundError(
                f"없는 거래 id 입니다: {tx_id}",
                "list 명령으로 id 를 확인하세요. 형식은 TX-000001 입니다.",
            )
        return tx

    # ---------- 수정 / 삭제 ----------

    def update(
        self,
        tx_id: str,
        *,
        date: str | None = None,
        tx_type: str | None = None,
        category: str | None = None,
        amount: str | int | None = None,
        memo: str | None = None,
        tags: str | None = None,
    ) -> tuple[Transaction, Transaction]:
        """옵션으로 준 필드만 바꾼다. (수정 전, 수정 후)를 돌려준다.

        update 방식은 '옵션 기반(안 A)'으로 고정했다. README 에 명시.
        이유: 대화형은 한 필드만 고치려 해도 전부 다시 물어보게 되고,
              쉘 히스토리로 재실행할 수 없어 반복 작업에 불리하다.
        """
        before = self.get(tx_id)
        # dataclass 는 그냥 대입하면 원본이 바뀌므로, 비교용으로 복사본을 만든다
        after = Transaction(**before.to_dict())

        changed = False
        if date is not None:
            after.date = validate_date(date)
            changed = True
        if tx_type is not None:
            after.type = validate_type(tx_type)
            changed = True
        if category is not None:
            after.category = self.categories.ensure_exists(category)
            changed = True
        if amount is not None:
            after.amount = validate_amount(amount)
            changed = True
        if memo is not None:
            after.memo = memo.strip()
            changed = True
        if tags is not None:
            after.tags = parse_tags(tags)
            changed = True

        if not changed:
            raise ValidationError(
                "수정할 항목이 없습니다.",
                "--date --type --category --amount --memo --tags 중 하나 이상을 주세요.",
            )

        def replaced() -> Iterator[Transaction]:
            for tx in self.repo.stream():
                yield after if tx.id == tx_id else tx

        self.repo.rewrite(replaced())
        return before, after

    def delete(self, tx_id: str) -> Transaction:
        """먼저 존재를 확인하고, 그 줄만 빼고 전체를 다시 쓴다.

        '없는 id'를 먼저 걸러내는 이유: 없는데도 파일을 통째로 다시 쓰는 낭비를 막고,
        사용자에게 정확한 메시지를 주기 위해서다.
        """
        target = self.get(tx_id)

        def kept() -> Iterator[Transaction]:
            for tx in self.repo.stream():
                if tx.id != tx_id:
                    yield tx

        self.repo.rewrite(kept())
        return target

    # ---------- 집계 ----------

    def summarize(self, month: str, top: int, budget: Budget | None) -> MonthlySummary:
        """한 달치 요약을 계산한다.

        파일을 **한 번만** 훑으면서 수입/지출/카테고리별 합계를 동시에 누적한다.
        (수입 구하려고 한 번, 지출 구하려고 또 한 번 읽으면 두 배로 느려진다)
        """
        clean_month = validate_month(month)
        total_income = 0
        total_expense = 0
        per_category: dict[str, int] = defaultdict(int)
        count = 0

        for tx in self.stream(SearchFilter(month=clean_month)):
            count += 1
            if tx.type == "income":
                total_income += tx.amount
            else:
                total_expense += tx.amount
                per_category[tx.category] += tx.amount

        # 카테고리 수는 많아야 수십 개라 전체 정렬해도 부담이 없다.
        # 금액 내림차순, 같으면 이름 오름차순(결과가 실행할 때마다 달라지지 않도록)
        ranked = sorted(per_category.items(), key=lambda kv: (-kv[1], kv[0]))[:top]

        return MonthlySummary(
            month=clean_month,
            total_income=total_income,
            total_expense=total_expense,
            top_expenses=ranked,
            budget=budget.amount if budget else None,
            transaction_count=count,
        )


class BudgetService:
    """월 예산 규칙 담당."""

    def __init__(self, store: BudgetStore) -> None:
        self.store = store

    def set(self, month: str, amount: str | int) -> Budget:
        clean_month = validate_month(month)
        clean_amount = validate_amount(amount)
        return self.store.set(clean_month, clean_amount)

    def get(self, month: str) -> Budget | None:
        return self.store.get(validate_month(month))

    def list(self) -> list[Budget]:
        return sorted(self.store.read_all(), key=lambda b: b.month)


class ImportExportService:
    """CSV 가져오기/내보내기 담당.

    저장 포맷은 JSONL 인데 교환 포맷은 CSV 다. 둘을 구분하는 이유:
      - JSONL: 프로그램이 쓰기 좋은 형식 (목록형 tags 를 그대로 담을 수 있다)
      - CSV  : 사람과 엑셀이 읽기 좋은 형식 (교환용)
    """

    def __init__(self, tx_service: TransactionService) -> None:
        self.tx = tx_service

    def import_csv(self, source: Path) -> tuple[int, list[str]]:
        """CSV 를 읽어 거래를 일괄 등록한다. (성공 건수, 건너뛴 이유 목록)

        한 줄이 잘못되어도 **전체를 중단하지 않는다.** 잘못된 줄만 이유와 함께 건너뛴다.
        100줄 중 1줄이 틀렸다고 99줄을 버리는 것은 사용자에게 도움이 되지 않는다.
        """
        if not source.exists():
            raise NotFoundError(
                f"가져올 파일이 없습니다: {source}",
                "경로를 확인하세요. 예: --from ./samples/import_sample.csv",
            )

        imported = 0
        skipped: list[str] = []
        try:
            with source.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise ValidationError(
                        "CSV 에 헤더 줄이 없습니다.",
                        f"첫 줄에 다음 헤더가 있어야 합니다: {','.join(config.CSV_COLUMNS)}",
                    )
                missing = [c for c in config.CSV_REQUIRED if c not in reader.fieldnames]
                if missing:
                    raise ValidationError(
                        f"CSV 에 필수 열이 없습니다: {', '.join(missing)}",
                        f"필수 열: {', '.join(config.CSV_REQUIRED)}",
                    )

                # id 는 한 번만 계산하고 메모리에서 증가시킨다.
                # 줄마다 next_id() 를 부르면 그때마다 파일 전체를 스캔해서 O(n*m) 이 된다.
                next_no = int(self.tx.repo.next_id()[3:])
                new_rows: list[Transaction] = []

                for line_no, row in enumerate(reader, start=2):  # 2 = 헤더 다음 줄
                    try:
                        tx = Transaction(
                            id=f"TX-{next_no:06d}",
                            date=validate_date(row.get("date", "")),
                            type=validate_type(row.get("type", "")),
                            amount=validate_amount(row.get("amount", "")),
                            category=self.tx.categories.ensure_exists(row.get("category", "")),
                            memo=(row.get("memo") or "").strip(),
                            tags=parse_tags(row.get("tags") or ""),
                        )
                    except (ValidationError, NotFoundError) as exc:
                        skipped.append(f"{line_no}번째 줄: {exc.message}")
                        continue
                    new_rows.append(tx)
                    next_no += 1
                    imported += 1
        except UnicodeDecodeError:
            raise ValidationError(
                f"CSV 인코딩을 읽을 수 없습니다: {source.name}",
                "UTF-8 로 저장해 주세요. (엑셀은 'CSV UTF-8' 형식으로 저장)",
            ) from None
        except csv.Error as exc:
            raise ValidationError(f"CSV 형식 오류: {exc}", "따옴표와 쉼표를 확인하세요.") from None

        for tx in new_rows:
            self.tx.repo.append(tx)
        return imported, skipped

    def export_csv(self, target: Path, flt: SearchFilter) -> int:
        """조건에 맞는 거래를 CSV 로 저장한다. 저장한 건수를 돌려준다.

        스트리밍으로 읽어 바로 쓴다. 메모리에 전체 목록을 만들지 않는다.
        """
        rows = sorted(self.tx.stream(flt), key=lambda tx: (tx.date, tx.id))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(config.CSV_COLUMNS))
                writer.writeheader()
                for tx in rows:
                    writer.writerow(
                        {
                            "date": tx.date,
                            "type": tx.type,
                            "category": tx.category,
                            "amount": tx.amount,
                            "memo": tx.memo,
                            "tags": ",".join(tx.tags),
                        }
                    )
        except OSError as exc:
            raise StorageError(
                f"CSV 를 저장하지 못했습니다: {target}",
                f"경로와 쓰기 권한을 확인하세요. ({exc.strerror})",
            ) from None
        return len(rows)


class RecurringService:
    """(보너스) 반복 내역 담당. 월급/월세처럼 매달 반복되는 거래를 규칙으로 저장한다."""

    def __init__(self, store: RecurringStore, tx_service: TransactionService) -> None:
        self.store = store
        self.tx = tx_service

    def add(
        self, *, tx_type: str, day: str | int, amount: str | int, category: str, memo: str = ""
    ) -> RecurringRule:
        rule = RecurringRule(
            id=self.store.next_id(),
            type=validate_type(tx_type),
            day=validate_day(day),
            amount=validate_amount(amount),
            category=self.tx.categories.ensure_exists(category),
            memo=memo.strip(),
            tags=["recurring"],
        )
        self.store.append(rule)
        return rule

    def list(self) -> list[RecurringRule]:
        return self.store.read_all()

    def remove(self, rule_id: str) -> RecurringRule:
        rules = self.store.read_all()
        target = next((r for r in rules if r.id == rule_id), None)
        if target is None:
            raise NotFoundError(
                f"없는 반복 규칙 id 입니다: {rule_id}",
                "recurring list 로 id 를 확인하세요. 형식은 RC-001 입니다.",
            )
        self.store.rewrite([r for r in rules if r.id != rule_id])
        return target

    def generate(self, month: str) -> tuple[list[Transaction], list[str]]:
        """해당 월에 반복 거래를 실제로 만들어 넣는다. (생성된 거래, 건너뛴 이유)

        이미 같은 규칙으로 만든 거래가 그 달에 있으면 건너뛴다.
        같은 명령을 두 번 실행해도 결과가 같아야(멱등) 사용자가 안심하고 쓸 수 있다.
        """
        clean_month = validate_month(month)
        rules = self.store.read_all()
        if not rules:
            return [], ["등록된 반복 규칙이 없습니다."]

        # 그 달에 이미 있는 (규칙id) 목록을 한 번의 스캔으로 모은다
        existing_memos = {
            tx.memo for tx in self.tx.stream(SearchFilter(month=clean_month)) if "recurring" in tx.tags
        }

        created: list[Transaction] = []
        skipped: list[str] = []
        for rule in rules:
            marker = f"[{rule.id}] {rule.memo}".strip()
            if marker in existing_memos:
                skipped.append(f"{rule.id}: 이미 {clean_month} 에 생성되어 있습니다.")
                continue
            day = self._clamp_day(clean_month, rule.day)
            tx = self.tx.add(
                date=f"{clean_month}-{day:02d}",
                tx_type=rule.type,
                category=rule.category,
                amount=rule.amount,
                memo=marker,
                tags=["recurring"],
            )
            created.append(tx)
        return created, skipped

    @staticmethod
    def _clamp_day(month: str, day: int) -> int:
        """31일 규칙인데 2월이면 그 달의 마지막 날로 당긴다.

        이런 경계 처리를 빼먹으면 2월 31일 같은 날짜가 만들어져 검증에서 터진다.
        """
        year, mon = int(month[:4]), int(month[5:7])
        if mon == 12:
            next_month_first = date_cls(year + 1, 1, 1)
        else:
            next_month_first = date_cls(year, mon + 1, 1)
        last_day = (next_month_first - timedelta(days=1)).day
        return min(day, last_day)


@dataclass
class Services:
    """서비스 묶음. CLI 가 이것 하나만 들고 다니면 된다."""

    data_dir: Path
    transactions: TransactionService
    categories: CategoryService
    budgets: BudgetService
    io: ImportExportService
    recurring: RecurringService


def build_services(data_dir: Path) -> Services:
    """저장소와 서비스를 조립한다(의존성 주입).

    어떤 파일을 쓸지, 어떤 서비스가 어떤 저장소를 쓰는지 결정하는 곳이 여기 한 군데뿐이다.
    테스트할 때는 data_dir 만 임시 폴더로 바꾸면 실제 데이터를 건드리지 않는다.
    """
    tx_repo = TransactionRepository(data_dir / config.TRANSACTIONS_FILE)
    cat_store = CategoryStore(data_dir / config.CATEGORIES_FILE)
    budget_store = BudgetStore(data_dir / config.BUDGETS_FILE)
    recurring_store = RecurringStore(data_dir / config.RECURRING_FILE)

    categories = CategoryService(cat_store, tx_repo)
    transactions = TransactionService(tx_repo, categories)
    budgets = BudgetService(budget_store)
    io = ImportExportService(transactions)
    recurring = RecurringService(recurring_store, transactions)

    return Services(
        data_dir=data_dir,
        transactions=transactions,
        categories=categories,
        budgets=budgets,
        io=io,
        recurring=recurring,
    )


def initialize_storage(services: Services) -> list[str]:
    """첫 실행 준비. 저장 파일 3개(+1)를 만들고 기본 카테고리를 넣는다."""
    services.transactions.repo.ensure_file()
    services.categories.store.ensure_file()
    services.budgets.store.ensure_file()
    services.recurring.store.ensure_file()
    return services.categories.bootstrap()
