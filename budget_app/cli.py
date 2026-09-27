"""cli.py — CLI 계층. 사용자의 입력을 받고 결과를 보여주는 일'만' 한다.

■ 이 계층의 책임
  1) 명령줄 인자를 해석한다 (argparse)
  2) 대화형으로 값을 물어본다 (input)
  3) 서비스에게 시킨다
  4) 서비스가 돌려준 객체를 formatters 로 예쁘게 출력한다

  계산도, 파일 접근도 여기서 하지 않는다. 그래서 이 파일에는 json/open 이 없다.

■ argparse 를 쓰는 이유
  - sys.argv 를 직접 파싱하면 --help, 타입 변환, 오타 안내를 전부 손으로 만들어야 한다.
  - argparse 는 서브커맨드(add/list/...)마다 --help 를 자동으로 만들어 준다.
    → 과제 요구: "모든 명령은 --help 로 사용 방법이 출력되어야 한다"

■ 옵션 표기
  과제 제약에 따라 모든 옵션은 리눅스 표준인 `--` 로 통일했다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, NoReturn

from . import config
from .decorators import configure_logging, handle_errors, log_command, measure_time
from .errors import AppError, NotFoundError, ValidationError
from .formatters import (
    format_recurring,
    format_summary,
    format_transaction_line,
    format_transactions,
    render_table,
    won,
)
from .repository import backup_directory
from .services import SearchFilter, Services, build_services, initialize_storage
from .validators import (
    validate_amount,
    validate_date,
    validate_date_range,
    validate_month,
    validate_type,
)

# ============================================================
# 대화형 입력 도우미
# ============================================================


def _input(prompt: str) -> str:
    """input() 을 감싸서 Ctrl+D(EOF)를 '취소'로 처리한다.

    감싸지 않으면 EOFError 스택트레이스가 그대로 화면에 뜬다.
    """
    try:
        return input(prompt)
    except EOFError:
        print()
        raise AppError("입력이 중단되었습니다.", "다시 실행해 주세요.") from None


def prompt_until_valid(
    label: str,
    convert: Callable[[str], object],
    *,
    allow_empty: bool = False,
    default: str = "",
) -> object:
    """올바른 값이 들어올 때까지 다시 물어본다.

    과제 요구: "날짜 형식 오류, 음수/0 금액 ... 은 재입력 요구 또는 오류 메시지 출력으로 처리"
    → 여기서는 **재입력 요구** 쪽을 택했다. 한 글자 틀렸다고 처음부터 다시 시키는 것은
      사용자에게 불친절하기 때문이다.
    """
    while True:
        raw = _input(label).strip()
        if not raw:
            if allow_empty:
                return convert(default) if default else ""
            print("[오류] 값을 입력해 주세요.")
            continue
        try:
            return convert(raw)
        except ValidationError as exc:
            print(f"[오류] {exc.message}")
            if exc.hint:
                print(f"[힌트] {exc.hint}")


def prompt_category(services: Services) -> str:
    """등록된 카테고리 중 하나를 고를 때까지 물어본다."""
    available = services.categories.list()
    print(f"  (사용 가능: {', '.join(available) if available else '없음'})")
    while True:
        raw = _input("카테고리: ").strip()
        if not raw:
            print("[오류] 카테고리를 입력해 주세요.")
            continue
        try:
            return services.categories.ensure_exists(raw)
        except NotFoundError as exc:
            print(f"[오류] {exc.message}")
            print(f"[힌트] {exc.hint}")


# ============================================================
# 명령 처리 함수들
# ============================================================
# 각 함수에 데코레이터가 두 개씩 붙는다.
#   @log_command  : 언제 실행되고 어떻게 끝났는지 로그 파일에 기록
#   @measure_time : 걸린 시간 측정 (--verbose 면 화면에도)
# 예외 처리(@handle_errors)는 맨 아래 main() 한 곳에만 붙인다.


@log_command
@measure_time
def cmd_add(args: argparse.Namespace, services: Services) -> None:
    """거래 추가 — 대화형 입력이 기본 방식이다."""
    print("거래를 추가합니다. (Ctrl+C 로 취소)")
    date = prompt_until_valid("날짜(YYYY-MM-DD): ", validate_date)
    tx_type = prompt_until_valid("타입(income/expense): ", validate_type)
    category = prompt_category(services)
    amount = prompt_until_valid("금액(양수): ", validate_amount)
    memo = _input("메모(선택): ").strip()
    tags = _input("태그(쉼표로 구분, 없으면 엔터): ").strip()

    tx = services.transactions.add(
        date=str(date),
        tx_type=str(tx_type),
        category=category,
        amount=int(amount),  # type: ignore[arg-type]
        memo=memo,
        tags=tags,
    )
    print(f"\n[저장 완료] id={tx.id}")
    print(format_transaction_line(tx))


@log_command
@measure_time
def cmd_list(args: argparse.Namespace, services: Services) -> None:
    """거래 목록 — 최신순, 스트리밍 처리."""
    rows = services.transactions.latest(args.limit)
    if not rows:
        print("표시할 거래가 없습니다.")
        print("[힌트] add 명령으로 첫 거래를 추가해 보세요.")
        return
    print(format_transactions(rows))
    print(f"\n총 {len(rows)}건 (최신순, --limit {args.limit})")


@log_command
@measure_time
def cmd_search(args: argparse.Namespace, services: Services) -> None:
    """조건 검색 — 기간/카테고리/타입/키워드/태그."""
    date_from, date_to = validate_date_range(args.date_from, args.date_to)
    flt = SearchFilter(
        date_from=date_from,
        date_to=date_to,
        category=args.category,
        tx_type=validate_type(args.type) if args.type else None,
        keyword=args.q,
        tag=args.tag,
    )
    rows = services.transactions.latest(args.limit, flt)
    if not rows:
        print("조건에 맞는 거래가 없습니다.")
        print("[힌트] 조건을 줄여보세요. (예: --category 만으로 먼저 확인)")
        return
    print(format_transactions(rows))
    print(f"\n총 {len(rows)}건 (최신순)")


@log_command
@measure_time
def cmd_summary(args: argparse.Namespace, services: Services) -> None:
    """월별 요약 — 예산이 있으면 사용률/초과 경고까지."""
    month = validate_month(args.month)
    budget = services.budgets.get(month)
    summary = services.transactions.summarize(month, args.top, budget)

    if summary.transaction_count == 0:
        print(f"[{month}] 데이터 없음")
        print("[힌트] 해당 월에 등록된 거래가 없습니다. list 명령으로 전체를 확인해 보세요.")
        return
    print(format_summary(summary))


@log_command
@measure_time
def cmd_budget(args: argparse.Namespace, services: Services) -> None:
    """예산 설정/조회."""
    if args.budget_command == "set":
        budget = services.budgets.set(args.month, args.amount)
        print(f"[저장 완료] {budget.month} 예산 {won(budget.amount)}")
        print(f"[힌트] summary --month {budget.month} 로 사용률을 확인하세요.")
    else:  # list
        budgets = services.budgets.list()
        if not budgets:
            print("설정된 예산이 없습니다.")
            print("[힌트] budget set --month YYYY-MM --amount <금액>")
            return
        print(
            render_table(
                ["월", "예산"],
                [[b.month, f"{b.amount:,}원"] for b in budgets],
                ["left", "right"],
            )
        )


@log_command
@measure_time
def cmd_category(args: argparse.Namespace, services: Services) -> None:
    """카테고리 관리 — add / list / remove."""
    if args.category_command == "add":
        name = args.name or _input("카테고리명: ").strip()
        created = services.categories.add(name)
        print(f"[저장 완료] category={created}")
    elif args.category_command == "list":
        names = services.categories.list()
        if not names:
            print("등록된 카테고리가 없습니다.")
            return
        for name in names:
            used = services.categories.usage_count(name)
            print(f"- {name} ({used}건)")
    else:  # remove
        name, moved = services.categories.remove(args.name, args.replace_with)
        if moved:
            print(f"[삭제 완료] category={name} (거래 {moved}건을 '{args.replace_with}' 로 옮김)")
        else:
            print(f"[삭제 완료] category={name}")


@log_command
@measure_time
def cmd_update(args: argparse.Namespace, services: Services) -> None:
    """거래 수정 — 옵션 기반(안 A로 고정, README 명시)."""
    before, after = services.transactions.update(
        args.id,
        date=args.date,
        tx_type=args.type,
        category=args.category,
        amount=args.amount,
        memo=args.memo,
        tags=args.tags,
    )
    print(f"[수정 완료] id={after.id}")
    print(f"  변경 전: {format_transaction_line(before)}")
    print(f"  변경 후: {format_transaction_line(after)}")


@log_command
@measure_time
def cmd_delete(args: argparse.Namespace, services: Services) -> None:
    """거래 삭제 — 없는 id 는 오류 메시지로 처리."""
    removed = services.transactions.delete(args.id)
    print(f"[삭제 완료] id={removed.id}")
    print(f"  {format_transaction_line(removed)}")


@log_command
@measure_time
def cmd_import(args: argparse.Namespace, services: Services) -> None:
    """CSV 가져오기 — 잘못된 줄은 이유와 함께 건너뛴다."""
    imported, skipped = services.io.import_csv(Path(args.source))
    print(f"[완료] imported={imported}, skipped={len(skipped)}")
    if skipped:
        print("\n건너뛴 줄:")
        for reason in skipped[:10]:  # 너무 많으면 화면을 덮으므로 10건만
            print(f"  - {reason}")
        if len(skipped) > 10:
            print(f"  ... 외 {len(skipped) - 10}건 (자세한 내용은 data/app.log)")


@log_command
@measure_time
def cmd_export(args: argparse.Namespace, services: Services) -> None:
    """CSV 내보내기 — 기간 조건이 반드시 하나는 있어야 한다."""
    if not (args.month or args.date_from or args.date_to):
        raise ValidationError(
            "내보낼 기간 조건이 없습니다.",
            "--month YYYY-MM 또는 --from YYYY-MM-DD --to YYYY-MM-DD 중 하나는 필요합니다.",
        )
    date_from, date_to = validate_date_range(args.date_from, args.date_to)
    flt = SearchFilter(
        month=validate_month(args.month) if args.month else None,
        date_from=date_from,
        date_to=date_to,
    )
    target = Path(args.out)
    count = services.io.export_csv(target, flt)
    if count == 0:
        print(f"[완료] {target} (0 records)")
        print("[힌트] 조건에 맞는 거래가 없습니다. 기간을 넓혀보세요.")
        return
    print(f"[완료] {target} ({count} records)")


@log_command
@measure_time
def cmd_backup(args: argparse.Namespace, services: Services) -> None:
    """(보너스) 저장 파일을 타임스탬프 폴더로 복사한다."""
    target, copied = backup_directory(services.data_dir, Path(args.backup_dir))
    print(f"[백업 완료] {target} ({copied}개 파일)")
    print("[힌트] 복구하려면 이 폴더의 .jsonl 파일을 data 폴더로 덮어쓰면 됩니다.")


@log_command
@measure_time
def cmd_recurring(args: argparse.Namespace, services: Services) -> None:
    """(보너스) 반복 내역 규칙 관리와 생성."""
    if args.recurring_command == "add":
        rule = services.recurring.add(
            tx_type=args.type,
            day=args.day,
            amount=args.amount,
            category=args.category,
            memo=args.memo or "",
        )
        print(f"[저장 완료] id={rule.id} (매달 {rule.day}일 {rule.category} {won(rule.amount)})")
    elif args.recurring_command == "list":
        rules = services.recurring.list()
        if not rules:
            print("등록된 반복 규칙이 없습니다.")
            print("[힌트] recurring add --type expense --day 25 --amount 500000 --category rent")
            return
        print(format_recurring(rules))
    elif args.recurring_command == "remove":
        removed = services.recurring.remove(args.id)
        print(f"[삭제 완료] id={removed.id}")
    else:  # generate
        created, skipped = services.recurring.generate(args.month)
        print(f"[완료] created={len(created)}, skipped={len(skipped)}")
        for tx in created:
            print(f"  + {format_transaction_line(tx)}")
        for reason in skipped:
            print(f"  - {reason}")


# ============================================================
# 파서 구성
# ============================================================


def build_parser() -> argparse.ArgumentParser:
    """명령어와 옵션을 정의한다.

    parents=[common] 로 --data-dir/--verbose 를 모든 서브커맨드에 한 번에 붙인다.
    덕분에 `python -m budget_app list --data-dir ./other` 처럼
    명령 뒤에 옵션을 써도 동작한다.
    """
    common = argparse.ArgumentParser(add_help=False)
    # default=argparse.SUPPRESS 를 쓰는 이유 (argparse 의 유명한 함정)
    #   parents=[common] 은 같은 옵션을 메인 파서와 서브커맨드 양쪽에 '복사'한다.
    #   보통의 default 를 두면, 서브커맨드가 나중에 파싱되면서
    #   `--data-dir ./other list` 처럼 앞쪽에 준 값을 서브커맨드의 기본값이 덮어써 버린다.
    #   SUPPRESS 는 "사용자가 실제로 준 경우에만 속성을 만든다"는 뜻이라 덮어쓰기가 일어나지 않는다.
    #   대신 아무도 주지 않았을 때의 기본값은 main() 에서 getattr 로 채운다.
    common.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help=f"저장 폴더 (기본값: {config.DEFAULT_DATA_DIR})",
    )
    common.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="실행 시간 등 부가 정보 출력",
    )

    parser = argparse.ArgumentParser(
        prog="python -m budget_app",
        description="나만의 용돈 기입장 — 표준 라이브러리만 사용하는 콘솔 가계부",
        epilog="각 명령의 자세한 사용법: python -m budget_app <command> --help",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # ---- add ----
    p_add = sub.add_parser(
        "add",
        parents=[common],
        help="거래 추가 (대화형)",
        description="날짜/타입/카테고리/금액을 차례로 입력받아 거래를 저장합니다.",
        epilog="예) python -m budget_app add",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_add.set_defaults(func=cmd_add)

    # ---- list ----
    p_list = sub.add_parser(
        "list",
        parents=[common],
        help="거래 목록 (최신순)",
        description="거래를 최신순으로 출력합니다. 파일을 한 번에 읽지 않고 스트리밍 처리합니다.",
        epilog="예) python -m budget_app list --limit 5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_list.add_argument(
        "--limit", type=int, default=config.DEFAULT_LIMIT, help=f"출력 개수 (기본값: {config.DEFAULT_LIMIT})"
    )
    p_list.set_defaults(func=cmd_list)

    # ---- search ----
    p_search = sub.add_parser(
        "search",
        parents=[common],
        help="조건 검색",
        description="기간/카테고리/타입/메모키워드/태그로 거래를 검색합니다.",
        epilog=(
            "예) python -m budget_app search --category food --from 2026-09-01 --to 2026-09-30\n"
            "    python -m budget_app search --q 점심 --type expense"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # dest 를 date_from 으로 바꾸는 이유: 'from' 은 파이썬 예약어라 args.from 으로 못 읽는다
    p_search.add_argument("--from", dest="date_from", help="시작일 YYYY-MM-DD")
    p_search.add_argument("--to", dest="date_to", help="종료일 YYYY-MM-DD")
    p_search.add_argument("--category", help="카테고리 이름")
    p_search.add_argument("--type", choices=["income", "expense"], help="income 또는 expense")
    p_search.add_argument("--q", help="메모에 포함된 키워드")
    p_search.add_argument("--tag", help="태그")
    p_search.add_argument("--limit", type=int, default=config.DEFAULT_LIMIT, help="출력 개수")
    p_search.set_defaults(func=cmd_search)

    # ---- summary ----
    p_summary = sub.add_parser(
        "summary",
        parents=[common],
        help="월별 요약",
        description="총수입/총지출/잔액과 카테고리별 지출 TOP N을 출력합니다. 예산이 있으면 사용률도 표시합니다.",
        epilog="예) python -m budget_app summary --month 2026-09 --top 3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_summary.add_argument("--month", required=True, help="YYYY-MM")
    p_summary.add_argument(
        "--top", type=int, default=config.DEFAULT_TOP, help=f"상위 N개 (기본값: {config.DEFAULT_TOP})"
    )
    p_summary.set_defaults(func=cmd_summary)

    # ---- budget ----
    p_budget = sub.add_parser(
        "budget",
        parents=[common],
        help="월 예산 설정/조회",
        description="월 예산을 저장하고 조회합니다. summary 에서 사용률과 초과 경고에 쓰입니다.",
        epilog="예) python -m budget_app budget set --month 2026-09 --amount 500000",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    budget_sub = p_budget.add_subparsers(dest="budget_command", metavar="<set|list>")
    b_set = budget_sub.add_parser("set", parents=[common], help="예산 설정")
    b_set.add_argument("--month", required=True, help="YYYY-MM")
    b_set.add_argument("--amount", required=True, help="예산 금액(양수)")
    budget_sub.add_parser("list", parents=[common], help="예산 목록")
    p_budget.set_defaults(func=cmd_budget, budget_command="list")

    # ---- category ----
    p_cat = sub.add_parser(
        "category",
        parents=[common],
        help="카테고리 관리",
        description="카테고리를 추가/조회/삭제합니다. 사용 중인 카테고리는 대체 카테고리 없이 삭제할 수 없습니다.",
        epilog=(
            "예) python -m budget_app category add\n"
            "    python -m budget_app category add --name cafe\n"
            "    python -m budget_app category remove --name cafe --replace-with etc"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cat_sub = p_cat.add_subparsers(dest="category_command", metavar="<add|list|remove>")
    c_add = cat_sub.add_parser("add", parents=[common], help="카테고리 추가")
    c_add.add_argument("--name", help="카테고리명 (생략하면 대화형으로 물어봅니다)")
    cat_sub.add_parser("list", parents=[common], help="카테고리 목록")
    c_rm = cat_sub.add_parser("remove", parents=[common], help="카테고리 삭제")
    c_rm.add_argument("--name", required=True, help="삭제할 카테고리명")
    c_rm.add_argument("--replace-with", help="사용 중일 때 옮길 대체 카테고리")
    p_cat.set_defaults(func=cmd_category, category_command="list")

    # ---- update ----
    p_update = sub.add_parser(
        "update",
        parents=[common],
        help="거래 수정 (옵션 기반)",
        description="--id 로 거래를 지정하고, 준 옵션만 수정합니다.",
        epilog="예) python -m budget_app update --id TX-000001 --amount 18000 --memo 저녁",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_update.add_argument("--id", required=True, help="수정할 거래 id (예: TX-000001)")
    p_update.add_argument("--date", help="YYYY-MM-DD")
    p_update.add_argument("--type", choices=["income", "expense"])
    p_update.add_argument("--category")
    p_update.add_argument("--amount")
    p_update.add_argument("--memo")
    p_update.add_argument("--tags", help="쉼표로 구분")
    p_update.set_defaults(func=cmd_update)

    # ---- delete ----
    p_delete = sub.add_parser(
        "delete",
        parents=[common],
        help="거래 삭제",
        description="--id 로 지정한 거래를 삭제합니다. 임시 파일 교체 방식이라 중간에 멈춰도 원본이 깨지지 않습니다.",
        epilog="예) python -m budget_app delete --id TX-000001",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_delete.add_argument("--id", required=True, help="삭제할 거래 id")
    p_delete.set_defaults(func=cmd_delete)

    # ---- import ----
    p_import = sub.add_parser(
        "import",
        parents=[common],
        help="CSV 가져오기",
        description="CSV 파일에서 거래를 일괄 등록합니다. 잘못된 줄은 이유와 함께 건너뜁니다.",
        epilog="예) python -m budget_app import --from ./samples/import_sample.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_import.add_argument("--from", dest="source", required=True, help="읽어올 CSV 경로")
    p_import.set_defaults(func=cmd_import)

    # ---- export ----
    p_export = sub.add_parser(
        "export",
        parents=[common],
        help="CSV 내보내기",
        description="조건에 맞는 거래를 CSV로 저장합니다. 기간 조건이 최소 하나는 필요합니다.",
        epilog="예) python -m budget_app export --out export.csv --month 2026-09",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_export.add_argument("--out", required=True, help="저장할 CSV 경로")
    p_export.add_argument("--month", help="YYYY-MM")
    p_export.add_argument("--from", dest="date_from", help="시작일 YYYY-MM-DD")
    p_export.add_argument("--to", dest="date_to", help="종료일 YYYY-MM-DD")
    p_export.set_defaults(func=cmd_export)

    # ---- backup (보너스) ----
    p_backup = sub.add_parser(
        "backup",
        parents=[common],
        help="[보너스] 저장 파일 백업",
        description="data 폴더의 저장 파일을 타임스탬프 폴더로 복사합니다.",
        epilog="예) python -m budget_app backup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_backup.add_argument(
        "--backup-dir", default=str(config.DEFAULT_BACKUP_DIR), help="백업 폴더 (기본값: ./backup)"
    )
    p_backup.set_defaults(func=cmd_backup)

    # ---- recurring (보너스) ----
    p_rec = sub.add_parser(
        "recurring",
        parents=[common],
        help="[보너스] 반복 내역",
        description="월급/월세처럼 매달 반복되는 거래를 규칙으로 등록하고 특정 월에 자동 생성합니다.",
        epilog=(
            "예) python -m budget_app recurring add --type expense --day 25 --amount 500000 --category rent --memo 월세\n"
            "    python -m budget_app recurring generate --month 2026-10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rec_sub = p_rec.add_subparsers(dest="recurring_command", metavar="<add|list|remove|generate>")
    r_add = rec_sub.add_parser("add", parents=[common], help="반복 규칙 추가")
    r_add.add_argument("--type", required=True, choices=["income", "expense"])
    r_add.add_argument("--day", required=True, help="매달 며칠 (1~31)")
    r_add.add_argument("--amount", required=True)
    r_add.add_argument("--category", required=True)
    r_add.add_argument("--memo")
    rec_sub.add_parser("list", parents=[common], help="반복 규칙 목록")
    r_rm = rec_sub.add_parser("remove", parents=[common], help="반복 규칙 삭제")
    r_rm.add_argument("--id", required=True, help="규칙 id (예: RC-001)")
    r_gen = rec_sub.add_parser("generate", parents=[common], help="해당 월에 반복 거래 생성")
    r_gen.add_argument("--month", required=True, help="YYYY-MM")
    p_rec.set_defaults(func=cmd_recurring, recurring_command="list")

    return parser


# ============================================================
# 진입점
# ============================================================


@handle_errors
def main(argv: list[str] | None = None) -> int:
    """프로그램의 시작점. 정상 종료면 0을 돌려준다.

    @handle_errors 가 가장 바깥에 있으므로, 아래 어디에서 AppError 가 나도
    [오류]/[힌트] 형식으로 출력되고 정해진 종료 코드로 끝난다.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    # SUPPRESS 때문에 속성이 없을 수 있으므로 getattr 로 기본값을 채운다
    data_dir = Path(getattr(args, "data_dir", str(config.DEFAULT_DATA_DIR))).expanduser()
    verbose = getattr(args, "verbose", False)
    configure_logging(data_dir / config.LOG_FILE, verbose=verbose)

    services = build_services(data_dir)
    created_categories = initialize_storage(services)
    if created_categories:
        print(f"[초기화] 저장 폴더를 만들었습니다: {data_dir}")
        print(f"[초기화] 기본 카테고리를 등록했습니다: {', '.join(created_categories)}")
        print()

    args.func(args, services)
    return 0


def run() -> NoReturn:
    """python -m budget_app 로 실행될 때 호출된다."""
    sys.exit(main())
