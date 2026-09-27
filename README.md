# 나만의 용돈 기입장 (budget_app)

> Codyssey AI 올인원 2기 · 본과정 AI·SW 기초 · **Python과 Git 심화** 미션
> 표준 라이브러리만으로 만든 콘솔 가계부. 파일 기반 영구 저장 + 제너레이터 스트리밍 + 데코레이터 + 타입 힌트.

## 실행 방법

```bash
# 파이썬 3.10 이상 (3.9 에서도 동작하도록 from __future__ import annotations 사용)
cd budget-app
python -m budget_app --help          # 전체 명령 보기
python -m budget_app add             # 첫 거래 추가 (대화형)
```

첫 실행 시 `./data` 폴더와 저장 파일이 **자동 생성**되고, 기본 카테고리
(`food, transport, rent, salary, etc`)가 등록됩니다. 별도 설치나 설정이 없습니다.

| 옵션 | 설명 |
| --- | --- |
| `--data-dir <경로>` | 저장 폴더 변경 (기본값 `./data`) |
| `--verbose` | 각 명령의 실행 시간을 함께 출력 |
| `--help` | 모든 명령/하위 명령에서 사용 가능 |

## 저장 파일 위치와 형식

저장 포맷은 **JSONL**(JSON Lines, 한 줄에 JSON 객체 하나)을 선택했습니다.
과제 요구대로 역할별로 파일을 **4개**로 분리했습니다.

| 파일 | 내용 | 한 줄 예시 |
| --- | --- | --- |
| `data/transactions.jsonl` | 거래 내역 | `{"id":"TX-000001","type":"expense","date":"2026-09-15","amount":15000,"category":"food","memo":"점심","tags":["meal"]}` |
| `data/categories.jsonl` | 카테고리 | `{"name":"food"}` |
| `data/budgets.jsonl` | 월 예산 | `{"month":"2026-09","amount":500000}` |
| `data/recurring.jsonl` | 반복 규칙 *(보너스)* | `{"id":"RC-001","type":"expense","day":25,"amount":500000,"category":"rent","memo":"월세","tags":["recurring"]}` |
| `data/app.log` | 실행 로그 | 화면에 찍지 않는 상세 기록 |

**왜 JSONL 인가?**
- 한 줄씩 읽으면 되므로 파일이 커져도 메모리가 늘지 않습니다 (스트리밍의 전제).
- 거래 추가는 **파일 끝에 한 줄 덧붙이기(append)** 로 끝납니다. 전체를 다시 쓸 필요가 없습니다.
- `tags` 같은 목록형 값을 그대로 담을 수 있습니다. CSV였다면 문자열로 인코딩해야 합니다.
- 교환용으로는 CSV를 쓰므로(`import`/`export`), 사람이 엑셀로 열어볼 길도 열려 있습니다.

## 주요 명령 예시

```bash
# 1. 거래 추가 (대화형)
$ python -m budget_app add
날짜(YYYY-MM-DD): 2026-09-15
타입(income/expense): expense
  (사용 가능: etc, food, rent, salary, transport)
카테고리: food
금액(양수): 15000
메모(선택): 점심
태그(쉼표로 구분, 없으면 엔터): meal

[저장 완료] id=TX-000001

# 2. 목록 (최신순, 스트리밍)
$ python -m budget_app list --limit 3

# 3. 검색
$ python -m budget_app search --category food --from 2026-09-01 --to 2026-09-30
$ python -m budget_app search --q 점심 --type expense --tag meal

# 4. 월별 요약
$ python -m budget_app summary --month 2026-09 --top 3

# 5. 예산
$ python -m budget_app budget set --month 2026-09 --amount 500000
$ python -m budget_app budget list

# 6. 카테고리
$ python -m budget_app category add --name cafe
$ python -m budget_app category list
$ python -m budget_app category remove --name cafe --replace-with etc

# 7. 수정 (옵션 기반)
$ python -m budget_app update --id TX-000001 --amount 18000 --memo "점심 (추가결제)"

# 8. 삭제
$ python -m budget_app delete --id TX-000001

# 9. 가져오기 / 내보내기
$ python -m budget_app import --from ./samples/import_sample.csv
$ python -m budget_app export --out export.csv --month 2026-09

# 10. 보너스
$ python -m budget_app backup
$ python -m budget_app recurring add --type expense --day 25 --amount 500000 --category rent --memo 월세
$ python -m budget_app recurring generate --month 2026-10
```

### update 방식은 "옵션 기반"으로 고정했습니다

과제에서 옵션 방식(안 A) / 대화형(안 B) 중 하나를 골라 문서에 고정하라고 했습니다.
**옵션 기반(안 A)** 을 선택했습니다.

```bash
python -m budget_app update --id TX-000001 [--date ...] [--type ...] [--category ...] \
                            [--amount ...] [--memo ...] [--tags ...]
```

- 한 필드만 고치려는데 전부 다시 물어보는 것은 비효율적입니다.
- 쉘 히스토리로 재실행할 수 있어 반복 작업에 유리합니다.
- 옵션을 하나도 주지 않으면 "수정할 항목이 없습니다" 오류로 종료합니다.

### 카테고리 파일이 비어 있을 때

과제에서 제시한 두 방안 중 **안 A(기본 카테고리 자동 생성)** 를 선택했습니다.
첫 실행에서 `add` 가 막히면 사용자가 무엇을 해야 할지 알기 어렵기 때문입니다.

## import/export CSV 스키마

공통: **UTF-8**, **헤더 포함**. 열 순서는 아래와 같이 고정됩니다.

| column | required | 설명 |
| --- | --- | --- |
| `date` | Y | `YYYY-MM-DD` |
| `type` | Y | `income` / `expense` |
| `category` | Y | 등록된 카테고리여야 함 |
| `amount` | Y | 양수 정수 |
| `memo` | N | 문자열 |
| `tags` | N | 쉼표(,) 구분 문자열. 값에 쉼표가 있으면 `"meal,lunch"` 처럼 따옴표로 감쌈 |

- `import` 는 잘못된 줄을 **건너뛰고 이유를 알려줍니다.** 100줄 중 1줄이 틀렸다고 99줄을 버리지 않습니다.
- `export` 는 `--month` 또는 `--from`/`--to` 중 **최소 하나**를 반드시 받습니다.

## 프로젝트 구조 (4계층)

```
budget-app/
├── budget_app/
│   ├── __main__.py      # python -m budget_app 진입점
│   ├── cli.py           # CLI 계층   — argparse, 대화형 입력, 출력
│   ├── services.py      # 서비스 계층 — 업무 규칙(검증·집계·예산·카테고리)
│   ├── repository.py    # 저장소 계층 — 파일 읽기/쓰기, 스트리밍, 원자적 교체
│   ├── models.py        # 모델 계층   — dataclass 로 데이터 모양 정의
│   ├── validators.py    # 입력 검증 규칙
│   ├── decorators.py    # 공통 관심사(예외/로그/시간 측정)
│   ├── formatters.py    # 출력 포맷(표 정렬)
│   ├── errors.py        # 예외 계층 + 종료 코드
│   └── config.py        # 기본값/상수
├── samples/             # import 예시 CSV
└── README.md
```

각 계층은 **아래쪽만 압니다.** CLI → 서비스 → 저장소 → 모델.
반대 방향 의존이 없어서, 저장 포맷을 CSV로 바꿔도 고칠 파일은 `repository.py` 하나입니다.
`services.py` 에 `print` 가 하나도 없고, `cli.py` 에 `open` 이 하나도 없는 것이 그 증거입니다.

## 설계에서 신경 쓴 것

### 1. 제너레이터 스트리밍 — 메모리가 파일 크기와 무관

`repository.stream()` 은 `yield` 로 한 건씩 내보냅니다. `list` 는 `heapq.nlargest(N, ...)` 로
받으므로, 파일이 아무리 커도 **메모리에 동시에 존재하는 것은 N건뿐**입니다.

10만 건(14.4MB) 파일로 실제 측정한 결과입니다.

| 방식 | 시간 | 최대 메모리 |
| --- | --- | --- |
| 스트리밍 + `heapq.nlargest(3)` (이 프로그램) | 1.37초 | **0.06 MB** |
| 전체를 리스트로 올린 뒤 정렬 | 1.62초 | 70.76 MB |

같은 결과를 내면서 메모리는 약 1,140배 적게 씁니다.

### 2. 원자적 교체 — 중간에 죽어도 데이터가 깨지지 않음

파일 한가운데 한 줄만 고치는 것은 불가능하므로 `update`/`delete` 는 전체를 다시 씁니다.
원본에 바로 덮어쓰다 중간에 멈추면 데이터가 반쯤 날아갑니다. 그래서

1. 같은 폴더에 임시 파일을 만들고
2. 거기에 전부 쓴 뒤 (`fsync` 로 디스크에 확실히 내려쓰고)
3. `os.replace` 로 원본 자리에 밀어 넣습니다 ← **이 순간이 원자적**

실패하면 임시 파일만 버려지고 원본은 그대로입니다. *(보너스 4번 과제 포함)*

### 3. 데코레이터로 공통 관심사 분리

```python
@log_command      # 언제 실행되고 어떻게 끝났는지 기록
@measure_time     # 걸린 시간 측정
def cmd_add(args, services): ...
```

예외 처리(`@handle_errors`)는 `main()` 한 곳에만 붙습니다. 가장 바깥에 있어야
안쪽에서 난 예외를 모두 잡을 수 있기 때문입니다.

### 4. 오류는 "원인 + 힌트", 스택트레이스는 로그 파일에만

```
$ python -m budget_app add
날짜(YYYY-MM-DD): 2024-13-40
[오류] 존재하지 않는 날짜입니다: 2024-13-40
[힌트] 월은 01~12, 일은 그 달의 마지막 날까지만 가능합니다.
날짜(YYYY-MM-DD):          ← 재입력을 요구한다
```

예상하지 못한 오류가 나도 화면에는 스택트레이스를 찍지 않고 `data/app.log` 에만 기록합니다.

### 종료 코드(exit code)

| 코드 | 의미 |
| --- | --- |
| 0 | 정상 |
| 1 | 예상하지 못한 오류 |
| 2 | 입력값 오류 (`ValidationError`) |
| 3 | 없는 데이터 (`NotFoundError`) |
| 4 | 규칙 충돌 (`ConflictError`) — 사용 중 카테고리 삭제 등 |
| 5 | 파일 입출력 실패 (`StorageError`) |
| 130 | 사용자가 Ctrl+C 로 중단 |

```bash
$ python -m budget_app delete --id TX-999999; echo $?
[오류] 없는 거래 id 입니다: TX-999999
[힌트] list 명령으로 id 를 확인하세요. 형식은 TX-000001 입니다.
3
```

## 보너스 과제

| # | 과제 | 구현 | 위치 |
| --- | --- | --- | --- |
| 1 | 백업 기능 | ✅ | `backup` 명령 → `backup/<타임스탬프>/` |
| 2 | 반복 내역 | ✅ | `recurring add/list/remove/generate` (2월 31일은 말일로 보정, 재실행해도 중복 생성 안 됨) |
| 3 | 출력 포맷 테이블 정렬 | ✅ | `formatters.py` — 한글 2칸 폭까지 계산 |
| 4 | 저장 원자성 강화 | ✅ | `repository.rewrite()` — 임시 파일 + `os.replace` |

## 제약 사항 준수

- 표준 라이브러리만 사용 (`json`, `csv`, `argparse`, `heapq`, `logging`, `dataclasses`, `pathlib`, `tempfile`, `unicodedata` …)
- `pip install` 필요한 외부 라이브러리 **없음**
- 저장 포맷 JSONL 1개, 저장 파일 3개 이상으로 분리
- 옵션 표기는 `--` 로 통일
- 스택트레이스 출력 금지, 오류 종료 시 exit code ≠ 0
- 모듈 10개로 분리 (요구: 3개 이상), 클래스 10개 이상 (요구: 2개 이상)
