"""__main__.py — `python -m budget_app` 로 실행할 때 파이썬이 찾는 파일.

왜 실제 코드를 여기 두지 않고 cli.run() 만 부르나?
  - 이 파일은 '실행 방법'일 뿐이고, 내용은 cli.py 가 갖는다.
  - 그래야 다른 파이썬 코드에서 `from budget_app.cli import main` 처럼 가져다 쓸 수 있다.
    (테스트 코드가 대표적인 예다)
"""

from .cli import run

if __name__ == "__main__":
    run()
