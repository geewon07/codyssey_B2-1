# 파일 기반 콘솔 가계부 (Budget App)

Python 3.10 이상과 **표준 라이브러리만** 사용하는 JSONL 기반 과제입니다. 필수 요구사항만 구현했습니다: 거래 추가/조회/수정/삭제, 검색, 월별 요약, 예산, 카테고리, CSV 입출력, 제너레이터, 데코레이터, 타입 힌트, 예외 처리.

## 1. 설치 및 실행

`budget_app_project/` 폴더에서 실행합니다. 외부 패키지 설치는 필요 없습니다.

```bash
python -m budget_app --help
python -m budget_app add
python -m budget_app list --limit 10
python -m budget_app summary --month 2026-11
```

macOS에서 `python` 명령어가 없으면 `python3`를 사용하세요.

저장 위치를 바꾸려면 다음과 같이 명령 **앞에** `--data-dir` 옵션을 적습니다. 기본 폴더는 `./data`이며 실행 시 자동 생성됩니다.

```bash
python -m budget_app --data-dir ./my_data add
python -m budget_app --data-dir ./my_data list
```

옵션은 전부 `--`로 시작합니다. 모든 명령/하위 명령에서 `--help`가 작동합니다. `--verbose`를 명령 앞에 넣으면 데코레이터의 실행 로그를 볼 수 있습니다.

## 2. 프로젝트 구조

```text
budget_app_project/
├── budget_app/
│   ├── __init__.py      # 패키지 선언
│   ├── __main__.py      # 실행 진입점
│   ├── cli.py           # 명령어 및 대화형 입력
│   ├── models.py        # Transaction dataclass
│   ├── repository.py    # JSONL 파일 저장 및 조회
│   ├── service.py       # CRUD, 검색, 집계, CSV 처리
│   ├── validators.py    # 타입/날짜/금액/카테고리 검증
│   ├── formatting.py    # 거래 내용을 단순 문자열로 출력
│   └── decorators.py    # 실행 로그/시간 측정 데코레이터
├── examples/
│   └── import_sample.csv
├── tests/
│   └── test_budget_app.py
└── README.md
```

역할은 다음과 같습니다. **모델**은 거래의 구조와 필드 유효성을 정의하고, **저장소**는 JSONL 파일을 읽고 씁니다. **서비스**는 거래와 카테고리 등 비즈니스 규칙을 검사하고, **CLI**는 명령어와 입력/출력을 담당합니다.

## 3. 데이터 저장

처음 실행하면 `./data` 폴더에 **정확히 다음 3개 파일**을 생성합니다.

- `transactions.jsonl`: 거래 1건을 JSON 객체 1줄로 저장
- `categories.jsonl`: 등록된 카테고리 1개를 1줄로 저장
- `budgets.jsonl`: 월 예산 1개를 1줄로 저장

기본 카테고리를 자동 생성하는 **안 A**를 적용했습니다. 기본 항목: `food`, `transport`, `housing`, `salary`, `shopping`, `health`, `leisure`, `other`.

거래 데이터 필드는 `id`, `type`, `date`, `amount`, `category`, `memo`, `tags`입니다. `memo`와 `tags`는 생략할 수 있습니다.

**수정/삭제 저장 정책:** 변경 전 기존 거래를 확인하고 검증한 다음 파일을 **일반적인 전체 재작성** 방식으로 덮어씁니다. 임시 파일을 이용한 rename 교체 방식은 적용하지 않았습니다. 따라서 수정/삭제 시 데이터 건수에 비례하는 메모리가 필요하며, 쓰기 도중 프로세스가 비정상 종료되면 파일 일부가 손상될 수 있습니다. 프로그램 실행 중 한 번에 하나의 쓰기 명령만 사용하세요.

## 4. 명령어

### add: 거래 추가 (대화형)

```bash
python -m budget_app add
```

```text
날짜(YYYY-MM-DD): 2026-11-12
타입(income/expense): expense
등록된 카테고리: food, health, housing, leisure, other, salary, shopping, transport
카테고리: food
금액(양수 정수): 15000
메모(선택): 점심
태그(쉼표 구분, 없으면 엔터): meal
[저장 완료] id=TX-...
```

잘못된 날짜·타입·금액·미등록 카테고리는 오류와 힌트를 출력한 뒤 **다시 입력**받습니다.

### list: 최신순 목록

```bash
python -m budget_app list
python -m budget_app list --limit 3
```

기본 20건이며 날짜 최신순입니다. `repository.transactions()`에서 `yield`로 거래를 한 건씩 읽고 `heapq.nlargest()`로 상위 N건만 유지합니다. 거래는 각 행을 `ID | 날짜 | 유형 | 카테고리 | 금액 | 메모 | 태그` 형태의 단순 문자열로 출력합니다.

### update: 거래 수정 (옵션 방식, 안 A)

```bash
python -m budget_app update --id TX-실제ID --amount 20000 --memo "저녁"
python -m budget_app update --id TX-실제ID --date 2026-11-10 --type income --category salary --tags "work,pay"
python -m budget_app update --id TX-실제ID --memo "" --tags ""
```

`update`는 **옵션 방식만** 사용합니다. 지정한 필드만 바꾸며 나머지는 유지합니다. ID가 없거나 수정 값이 유효하지 않으면 오류를 출력합니다.

### delete: 거래 삭제

```bash
python -m budget_app delete --id TX-실제ID
```

존재하지 않는 ID면 `없는 데이터` 오류를 출력하고 0이 아닌 코드로 종료합니다.

### search: 조건 검색

```bash
python -m budget_app search --from 2026-11-01 --to 2026-11-30
python -m budget_app search --category food --type expense
python -m budget_app search --q "점심" --tag meal
```

`--from`, `--to`, `--category`, `--type`, `--q`(메모 문자열), `--tag`를 조합할 수 있습니다. 모든 결과는 날짜 최신순입니다. `yield`로 한 건씩 읽고, 필요하면 일정 크기의 덩어리를 디스크에서 병합 정렬하여 전체 데이터를 한꺼번에 메모리에 적재하지 않습니다. 이 **검색 결과 순서 유지**는 필수 검색 요구사항의 일부입니다.

### summary / budget: 월별 요약과 예산

```bash
python -m budget_app budget set --month 2026-11 --amount 500000
python -m budget_app summary --month 2026-11 --top 3
```

수입, 지출, 잔액, 카테고리별 지출 TOP N을 보여줍니다. 해당 월 거래가 없으면 `데이터 없음`을 표시합니다. 예산이 등록된 월에는 사용률 및 초과 경고가 나옵니다. 월 예산은 `budgets.jsonl`에 영구 저장됩니다.

### category: 카테고리 관리

```bash
python -m budget_app category add
python -m budget_app category add --name books
python -m budget_app category list
python -m budget_app category remove --name books
```

거래에서 사용 중인 카테고리는 삭제할 수 없으며, 삭제하려면 해당 거래의 카테고리를 먼저 수정하거나 거래를 삭제해야 합니다.

### import / export: CSV 가져오기·내보내기

```bash
python -m budget_app import --from examples/import_sample.csv
python -m budget_app export --out exports/nov.csv --month 2026-11
python -m budget_app export --out exports/week.csv --from 2026-11-01 --to 2026-11-07
```

`export`는 `--month` 또는 `--from` + `--to` 중 한 방식을 반드시 입력해야 합니다. 파일은 **UTF-8, 헤더 포함**이며 고정된 CSV 열은 다음과 같습니다.

| 열 | 필수 | 의미 |
| --- | --- | --- |
| `date` | Y | YYYY-MM-DD |
| `type` | Y | income / expense |
| `category` | Y | 기존 등록 카테고리 |
| `amount` | Y | 양수 정수 |
| `memo` | N | 선택 문자열 |
| `tags` | N | 쉼표로 나눈 태그 |

CSV 열 안에 쉼표가 있다면 따옴표로 묶어야 합니다. 가져오기에서는 정상 행마다 새 거래 ID를 발급하고, 유효하지 않은 행은 건너뛴 후 건수를 알려줍니다. 필수 헤더 자체가 없으면 오류 처리하며 기존 거래는 변경하지 않습니다. 같은 CSV를 다시 가져오면 중복 거래가 추가될 수 있습니다.

## 5. 필수 개념 정리

**제너레이터와 스트리밍 (`repository.py`)**

```python
def jsonl_rows(path):
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)
```

`yield`는 값을 한 번에 모두 리스트로 만들지 않고 호출자가 요청할 때마다 다음 행을 제공합니다. 따라서 `list`와 `search`에서 대용량 파일을 줄 단위로 처리할 수 있습니다. 단, `list(generator)`로 변환하면 전체 메모리를 사용한다는 점은 주의해야 합니다.

**데코레이터 (`decorators.py`)**

```python
@logged_and_timed
def summary(self, month: str) -> Summary:
    ...
```

시간 측정과 실행 로그를 여러 서비스 메서드에서 반복 작성하지 않고 데코레이터로 분리했습니다. `--verbose` 옵션에서 로그를 확인할 수 있습니다.

**타입 힌트 (`service.py`)**

```python
def get(self, transaction_id: str) -> Transaction | None:
    ...

def list_latest(self, limit: int = 20) -> list[Transaction]:
    ...

def search(self, *, start: str | None = None, ...) -> Iterator[Transaction]:
    ...
```

반환 타입의 의미를 명확히 보여줍니다: `get`은 데이터가 없으면 `None`, `list_latest`는 리스트, `search`는 순차 처리 가능한 반복자입니다. 타입 힌트 자체가 실행 시 입력을 검증하지 않으므로 별도로 `validators.py`에서 검증합니다.

## 6. 오류 처리 및 테스트

- 날짜 형식 오류, 0·음수 금액, 잘못된 유형, 미등록 카테고리 등을 검사합니다.
- 오류는 스택트레이스 대신 `[오류]` 원인과 `[힌트]`를 출력합니다.
- 종료 코드: 정상 **0**, 유효성/파일 오류 **2**, 예상하지 못한 오류 **1**, 입력 중단 **130**.

```bash
python -m unittest discover -s tests -v
```

총 **12개 테스트**를 포함합니다. 초기화, CRUD/영속성, 잘못된 입력, 스트리밍 조회와 검색, 월별 요약, 예산, 카테고리 제약, CSV 입출력, 오류 코드, CLI 명령 구성 등을 확인합니다.
