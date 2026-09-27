"""decorators.py — 공통 관심사(횡단 관심사)를 함수에서 분리한다.

■ 데코레이터가 필요한 이유
  명령이 10개인데 각각에 이런 코드가 들어간다고 생각해 보자.

      def cmd_add(args):
          start = time.time()
          logger.info("add 시작")
          try:
              ...진짜 하고 싶은 일...
          except AppError as e:
              print(...); sys.exit(e.exit_code)
          finally:
              logger.info("add 끝 %.1fms", ...)

  '진짜 하고 싶은 일'은 몇 줄인데 그 주변 포장이 더 길다. 게다가 이 포장은 10개 명령에
  **똑같이 복사**된다. 로그 형식을 바꾸려면 10군데를 고쳐야 한다.

  데코레이터는 이 포장을 함수 바깥으로 빼낸다. 명령 함수는 자기 일만 하고,
  포장은 @ 한 줄로 붙는다. 이런 걸 '횡단 관심사(cross-cutting concern) 분리'라고 한다.

■ 쌓는 순서 (아래에서 위로 감싼다)
      @handle_errors      ← 가장 바깥. 아래 전부에서 나온 예외를 잡는다
      @log_command        ← 중간
      @measure_time       ← 가장 안쪽. 실제 함수에 가장 가깝다
      def cmd_add(...)
  실행 순서는 handle_errors → log_command → measure_time → 실제 함수 이고,
  끝나고 돌아올 때는 반대다. 예외를 잡는 쪽이 가장 바깥에 있어야 안쪽 예외를 다 잡는다.

■ functools.wraps 를 쓰는 이유
  데코레이터는 원래 함수를 다른 함수로 바꿔치기한다. 그대로 두면 함수 이름이
  전부 'wrapper' 가 되어 로그와 --help 설명이 망가진다. wraps 가 이름/독스트링을 옮겨준다.
"""

from __future__ import annotations

import functools
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from .errors import AppError

logger = logging.getLogger("budget_app")

# 데코레이터가 감싸는 함수의 타입을 유지하기 위한 타입 변수.
# 이게 없으면 데코레이터를 붙인 순간 편집기가 인자 정보를 잃어버린다.
F = TypeVar("F", bound=Callable[..., Any])

_verbose = False


def configure_logging(log_path: Path, verbose: bool = False) -> None:
    """로그를 파일에 남기도록 설정한다. CLI 가 시작할 때 한 번 부른다.

    콘솔에는 로그를 찍지 않는다. 사용자는 실행 결과만 보면 되고,
    디버깅용 기록(예외의 자세한 내용 포함)은 파일에 남긴다.
    → 과제 제약인 '스택트레이스 출력 금지'를 지키면서도 원인 추적은 가능하게 한 설계.
    """
    global _verbose
    _verbose = verbose
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    except OSError:
        # 로그를 못 남기는 것이 프로그램을 멈출 이유는 되지 않는다.
        logger.addHandler(logging.NullHandler())


def handle_errors(func: F) -> F:
    """예외를 사용자용 메시지로 바꾸고 종료 코드를 정한다.

    - AppError(우리가 의도한 오류): [오류] 원인 + [힌트] 해결 방법 을 출력하고 정해진 코드로 종료
    - 그 외 예외(버그): 스택트레이스를 화면에 뿌리지 않고 로그 파일에만 남긴다
    - KeyboardInterrupt(Ctrl+C): 오류가 아니라 사용자의 취소이므로 조용히 종료
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except AppError as exc:
            print(f"[오류] {exc.message}", file=sys.stderr)
            if exc.hint:
                print(f"[힌트] {exc.hint}", file=sys.stderr)
            logger.warning("%s: %s", type(exc).__name__, exc.message)
            sys.exit(exc.exit_code)
        except KeyboardInterrupt:
            print("\n[취소] 사용자가 중단했습니다.", file=sys.stderr)
            sys.exit(130)  # 130 = 128 + SIGINT(2). 쉘의 관례를 따른다
        except Exception as exc:  # noqa: BLE001  (최후의 방어선이므로 의도적으로 넓게 잡는다)
            print(f"[오류] 예상하지 못한 문제가 발생했습니다: {type(exc).__name__}", file=sys.stderr)
            print("[힌트] data/app.log 에 자세한 내용이 기록되었습니다.", file=sys.stderr)
            logger.exception("예상하지 못한 오류")  # 스택트레이스는 '파일에만' 남긴다
            sys.exit(1)

    return wrapper  # type: ignore[return-value]


def log_command(func: F) -> F:
    """어떤 명령이 언제 실행되고 어떻게 끝났는지 기록한다."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.info("명령 시작: %s", func.__name__)
        try:
            result = func(*args, **kwargs)
        except Exception:
            logger.info("명령 실패: %s", func.__name__)
            raise  # 여기서 삼키면 안 된다. 처리 책임은 handle_errors 에 있다
        logger.info("명령 완료: %s", func.__name__)
        return result

    return wrapper  # type: ignore[return-value]


def measure_time(func: F) -> F:
    """실행 시간을 잰다. --verbose 를 주면 화면에도 보여준다.

    perf_counter 를 쓰는 이유: time.time() 은 시스템 시계가 바뀌면 값이 튄다.
    perf_counter 는 '경과 시간' 측정 전용이라 그런 영향을 받지 않는다.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug("%s 소요 %.1fms", func.__name__, elapsed_ms)
            if _verbose:
                print(f"[시간] {func.__name__} {elapsed_ms:.1f}ms", file=sys.stderr)

    return wrapper  # type: ignore[return-value]
