"""repository.py — 저장소 계층. 파일을 읽고 쓰는 일'만' 한다.

■ 이 계층의 약속
  - 업무 규칙(예: 카테고리가 등록되어 있는지)은 여기서 판단하지 않는다. 그건 서비스 계층의 일이다.
  - 여기는 "줄 단위로 읽어서 객체로 준다 / 객체를 받아 줄로 쓴다"만 한다.
  - 그래서 저장 포맷을 JSONL -> CSV 로 바꿔도 고칠 파일은 이것 하나뿐이다.

■ 왜 JSONL(JSON Lines)인가?
  - 한 줄에 JSON 객체 하나. `{"id": "TX-000001", ...}\n{"id": "TX-000002", ...}\n`
  - **한 줄씩 읽으면 되므로 파일이 아무리 커도 메모리가 늘지 않는다.** (스트리밍의 전제)
  - 새 거래는 파일 끝에 한 줄 덧붙이면 끝이다(append). 전체를 다시 쓸 필요가 없다.
  - 일반 JSON 배열(`[{...},{...}]`)이었다면 한 건 추가에도 전체를 읽고 전체를 다시 써야 한다.
  - tags 처럼 목록형 값을 그대로 담을 수 있다. (CSV였다면 문자열로 인코딩해야 한다)

■ 제너레이터(yield)를 쓰는 이유
  - `return [모든 줄]` 은 파일 전체를 리스트로 메모리에 올린다. 10만 줄이면 10만 개 객체가 동시에 산다.
  - `yield` 는 한 건을 만들어 넘겨주고 그 자리에서 멈춘다. 다음 건은 호출자가 요구할 때 만든다.
  - 그래서 메모리 사용량이 **파일 크기와 무관**해지고, 조건을 만족하면 중간에 멈출 수도 있다.

■ update/delete 를 어떻게 안전하게 하나? (원자적 교체)
  - 파일 한가운데 한 줄만 고치는 것은 불가능하다(뒤 내용이 밀린다). 결국 전체를 다시 써야 한다.
  - 원본에 바로 덮어쓰다가 중간에 프로그램이 죽으면 **데이터가 반쯤 날아간다.**
  - 그래서 임시 파일에 먼저 다 쓰고, 마지막에 os.replace 로 이름을 바꿔치기한다.
    os.replace 는 같은 디스크 안에서 원자적(atomic)이다. 즉 성공 아니면 실패 둘 중 하나고,
    "반쯤 쓰인 파일"이 남지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Protocol, TypeVar

from .errors import StorageError
from .models import Budget, Category, RecurringRule, Transaction


class Serializable(Protocol):
    """저장소가 다룰 수 있는 객체의 '계약'.

    Protocol 은 상속 없이 '이 메서드만 있으면 통과'를 타입으로 표현한다.
    여기서는 to_dict() 만 있으면 어떤 객체든 저장할 수 있다는 뜻이다.
    타입 힌트가 문서 역할을 하는 대표적인 예.
    """

    def to_dict(self) -> dict[str, Any]: ...


T = TypeVar("T")


class JsonlStore:
    """JSONL 파일 하나를 담당하는 기본 저장소.

    아래 4개 저장소(거래/카테고리/예산/반복규칙)가 이 클래스를 물려받아
    '어떤 모델로 복원할지'만 다르게 지정한다. 파일 다루는 코드는 한 번만 쓴다.
    """

    def __init__(self, path: Path, from_dict: Callable[[dict[str, Any]], Any]) -> None:
        self.path = path
        self._from_dict = from_dict

    # ---------- 준비 ----------

    def ensure_file(self) -> bool:
        """파일이 없으면 빈 파일로 만든다. 새로 만들었으면 True.

        폴더까지 함께 만든다(parents=True). 첫 실행에서 사용자가 아무것도 준비하지 않아도
        프로그램이 스스로 자리를 잡게 하기 위해서다.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.touch()
                return True
            return False
        except OSError as exc:
            raise StorageError(
                f"저장 폴더를 만들 수 없습니다: {self.path.parent}",
                f"쓰기 권한을 확인하거나 --data-dir 로 다른 폴더를 지정하세요. ({exc.strerror})",
            ) from None

    # ---------- 읽기 (제너레이터) ----------

    def stream(self) -> Iterator[Any]:
        """파일을 한 줄씩 읽어 객체를 하나씩 내보낸다. ★ 이 프로그램의 심장

        `for line in f:` 자체가 이미 제너레이터다. 파일 전체를 읽지 않고
        디스크에서 한 줄씩 가져온다. 우리는 그 줄을 객체로 바꿔 yield 한다.

        호출한 쪽이 10건만 받고 멈추면, 나머지 줄은 **아예 읽지도 않는다.**
        """
        if not self.path.exists():
            return  # 파일이 없으면 '빈 스트림'. 예외를 던지지 않는 편이 호출부가 단순하다.
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue  # 빈 줄은 건너뛴다
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        raise StorageError(
                            f"저장 파일이 손상되었습니다: {self.path.name} {line_no}번째 줄",
                            "해당 줄을 지우거나, backup 명령으로 만든 백업에서 복구하세요.",
                        ) from None
                    yield self._from_dict(raw)
        except PermissionError:
            raise StorageError(
                f"파일을 읽을 권한이 없습니다: {self.path}",
                "파일 권한을 확인하세요. (ls -l 로 확인)",
            ) from None

    def read_all(self) -> list[Any]:
        """전체를 리스트로 읽는다.

        카테고리/예산처럼 **개수가 적은 것**에만 쓴다.
        거래 내역에는 절대 쓰지 않는다. 그게 스트리밍을 쓰는 이유이므로.
        """
        return list(self.stream())

    # ---------- 쓰기 ----------

    def append(self, item: Serializable) -> None:
        """파일 끝에 한 줄 덧붙인다. 기존 내용은 건드리지 않는다.

        ensure_ascii=False 를 주는 이유: 한글을 \\uXXXX 로 이스케이프하지 않고
        그대로 저장해 사람이 파일을 열어봐도 읽을 수 있게 하기 위해서다.
        """
        self.ensure_file()
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            raise StorageError(
                f"파일에 쓸 수 없습니다: {self.path}",
                f"디스크 공간과 쓰기 권한을 확인하세요. ({exc.strerror})",
            ) from None

    def rewrite(self, items: Iterable[Serializable]) -> int:
        """전체를 다시 쓴다. update/delete 가 사용한다. ★ 원자적 교체

        1) 같은 폴더에 임시 파일을 만든다  (다른 폴더면 os.replace 가 원자적이지 않을 수 있다)
        2) 거기에 전부 쓴다
        3) os.replace 로 원본 자리에 밀어 넣는다  ← 이 순간이 원자적이다

        중간에 프로그램이 죽어도 원본은 그대로 남는다. 임시 파일만 버려진다.
        items 를 제너레이터로 받기 때문에, 이 과정에서도 메모리에 전체가 올라오지 않는다.
        """
        self.ensure_file()
        count = 0
        tmp_path: str | None = None
        try:
            # delete=False: with 를 빠져나와도 파일을 남겨야 os.replace 로 옮길 수 있다
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = tmp.name
                for item in items:
                    tmp.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
                    count += 1
                tmp.flush()
                os.fsync(tmp.fileno())  # OS 버퍼에만 있던 내용을 디스크에 확실히 내려쓴다
            os.replace(tmp_path, self.path)  # ← 원자적 교체
            tmp_path = None
            return count
        except OSError as exc:
            raise StorageError(
                f"파일을 저장하지 못했습니다: {self.path}",
                f"디스크 공간과 쓰기 권한을 확인하세요. ({exc.strerror})",
            ) from None
        finally:
            # 실패했으면 임시 파일을 치운다. 원본은 손대지 않았으므로 안전하다.
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TransactionRepository(JsonlStore):
    """거래 내역 저장소. transactions.jsonl"""

    def __init__(self, path: Path) -> None:
        super().__init__(path, Transaction.from_dict)

    def stream(self) -> Iterator[Transaction]:  # type: ignore[override]
        """타입을 Transaction 으로 좁혀주는 덮어쓰기.

        동작은 부모와 같지만, 이 선언 덕분에 호출하는 쪽에서 tx.amount 를 쓸 때
        편집기가 자동완성과 오타 검사를 해준다. (타입 힌트의 실질적 이점)
        """
        return super().stream()

    def next_id(self) -> str:
        """다음 거래 id 를 만든다. TX-000001, TX-000002 ...

        별도의 '마지막 번호' 파일을 두지 않고 매번 스캔하는 이유:
          - 카운터 파일과 실제 데이터가 어긋나면(한쪽만 저장 실패) 중복 id 가 생긴다.
          - 데이터 자체가 유일한 진실이 되도록 했다. 대신 add 할 때 O(n) 스캔이 든다.
          - 개인 가계부 규모(수천~수만 건)에서는 체감되지 않는 비용이라 안전 쪽을 택했다.
        """
        max_no = 0
        for tx in self.stream():
            if tx.id.startswith("TX-"):
                try:
                    max_no = max(max_no, int(tx.id[3:]))
                except ValueError:
                    continue  # 손으로 고친 이상한 id 는 무시한다
        return f"TX-{max_no + 1:06d}"

    def find_by_id(self, tx_id: str) -> Transaction | None:
        """id 로 한 건을 찾는다. 찾으면 **즉시 멈춘다.**

        전체를 다 읽지 않는 것이 핵심이다. 이게 제너레이터의 두 번째 이점이다.
        """
        for tx in self.stream():
            if tx.id == tx_id:
                return tx
        return None


class CategoryStore(JsonlStore):
    """카테고리 저장소. categories.jsonl — 개수가 적어 전체 로드해도 된다."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, Category.from_dict)

    def names(self) -> list[str]:
        return [c.name for c in self.read_all()]

    def exists(self, name: str) -> bool:
        return name in self.names()


class BudgetStore(JsonlStore):
    """월 예산 저장소. budgets.jsonl"""

    def __init__(self, path: Path) -> None:
        super().__init__(path, Budget.from_dict)

    def get(self, month: str) -> Budget | None:
        for budget in self.stream():
            if budget.month == month:
                return budget
        return None

    def set(self, month: str, amount: int) -> Budget:
        """있으면 덮어쓰고 없으면 추가한다(upsert).

        같은 달 예산이 두 줄 생기지 않도록 전체를 다시 쓴다.
        예산은 건수가 적어서(월 1건) 전체 재작성 비용이 무시할 만하다.
        """
        new_budget = Budget(month=month, amount=amount)
        existing = self.read_all()
        replaced = False
        result: list[Budget] = []
        for budget in existing:
            if budget.month == month:
                result.append(new_budget)
                replaced = True
            else:
                result.append(budget)
        if not replaced:
            result.append(new_budget)
        result.sort(key=lambda b: b.month)
        self.rewrite(result)
        return new_budget


class RecurringStore(JsonlStore):
    """(보너스) 반복 내역 규칙 저장소. recurring.jsonl"""

    def __init__(self, path: Path) -> None:
        super().__init__(path, RecurringRule.from_dict)

    def next_id(self) -> str:
        max_no = 0
        for rule in self.read_all():
            if rule.id.startswith("RC-"):
                try:
                    max_no = max(max_no, int(rule.id[3:]))
                except ValueError:
                    continue
        return f"RC-{max_no + 1:03d}"


def backup_directory(data_dir: Path, backup_dir: Path) -> tuple[Path, int]:
    """(보너스) data 폴더의 모든 저장 파일을 타임스탬프 폴더로 복사한다.

    파일 기반 저장의 유일한 복구 수단이 백업이다.
    update/delete 가 전체 재작성을 하므로, 실수로 지운 경우 되돌릴 방법이 필요하다.
    """
    if not data_dir.exists():
        raise StorageError(
            f"백업할 데이터 폴더가 없습니다: {data_dir}",
            "먼저 add 명령으로 데이터를 하나 이상 만들어 주세요.",
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / stamp
    try:
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for item in sorted(data_dir.glob("*.jsonl")):
            shutil.copy2(item, target / item.name)
            copied += 1
        return target, copied
    except OSError as exc:
        raise StorageError(
            f"백업에 실패했습니다: {target}",
            f"쓰기 권한과 디스크 공간을 확인하세요. ({exc.strerror})",
        ) from None
