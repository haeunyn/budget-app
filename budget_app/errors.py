"""errors.py — 이 프로그램이 사용하는 예외와 종료 코드.

■ 왜 예외 클래스를 따로 만드나?
  - 파이썬 기본 예외(ValueError 등)만 쓰면 "무엇이 잘못됐는지"는 알아도
    "사용자에게 뭐라고 말해줘야 하는지"를 코드가 모른다.
  - 그래서 메시지(message)와 함께 **해결 힌트(hint)** 를 예외가 직접 들고 다니게 했다.
  - 덕분에 CLI는 예외를 잡아서 그대로 출력하기만 하면 된다. (decorators.handle_errors)

■ 종료 코드(exit code)를 나누는 이유
  - 쉘 스크립트나 CI가 `echo $?` 로 실패 원인을 구분할 수 있다.
  - 과제 제약: 정상 종료 0, 오류 종료는 0이 아닌 값.
"""

from __future__ import annotations


class AppError(Exception):
    """이 프로그램이 의도적으로 발생시키는 모든 오류의 부모.

    사용자에게 보여줄 message 와 hint 를 함께 담는다.
    """

    exit_code: int = 1

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message: str = message
        self.hint: str = hint


class ValidationError(AppError):
    """입력값이 규칙에 맞지 않을 때. (날짜 형식, 음수 금액, 잘못된 타입 등)"""

    exit_code = 2


class NotFoundError(AppError):
    """요청한 데이터가 없을 때. (없는 거래 id, 없는 카테고리 등)"""

    exit_code = 3


class ConflictError(AppError):
    """규칙상 지금 할 수 없는 작업일 때. (사용 중인 카테고리 삭제, 중복 카테고리 등)"""

    exit_code = 4


class StorageError(AppError):
    """파일을 읽거나 쓰지 못했을 때. (권한 없음, 깨진 JSON 등)"""

    exit_code = 5
