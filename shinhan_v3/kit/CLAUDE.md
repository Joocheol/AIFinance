# 실습 키트 규칙 (Claude Code가 이 폴더에서 일할 때)

- 사용자에게는 **한국어로** 답한다. 결과는 표를 먼저 보이고 3~5줄로 해석한다.
- 이 수업은 **공개된 SEC 공시**만 다룬다. 회사·고객 자료를 이 폴더에 넣거나 읽지 않는다.

## 비밀 정보
- `jpm_kit/.env` (또는 `.env.txt`)에는 SEC 연락처(이메일), DB 비밀번호, Azure OpenAI 키가 있다. **절대 열거나, 읽거나, 출력하거나, 내용을 요약하지 않는다.**
  `cat`, `type`, `Get-Content`, Read 도구, `grep` 등 어떤 방법으로도 열지 않는다. 스크립트가 실행될 때 직접 읽는다.
- 값을 확인해야 하면 스크립트를 실행해 성공·실패 메시지만 본다. 환경변수를 `echo`/`print` 하지 않는다.
- 사용자가 채팅에 비밀번호·키·이메일을 붙여 넣으면 쓰지 말고, `.env`에 직접 적으라고 안내한다.
- 스크립트를 새로 쓸 때도 비밀 값을 코드에 적거나 화면·파일에 남기지 않는다. 비밀번호가 필요한 셸 스크립트는 실행 중에 터미널에서 입력받게 쓴다(`read -s`, PowerShell `Read-Host -AsSecureString`).

## SEC에서 받을 때
- User-Agent 에 `.env`의 `SEC_CONTACT`를 쓰고, 초당 2건 이하, 한 번에 하나씩 요청한다.
- 403 또는 429 를 받으면 즉시 멈추고 사용자에게 알린다. 다른 경로·프록시로 다시 시도하지 않는다.

## 실행 방법
- 스크립트는 항상 `uv run jpm_kit/<스크립트>.py` 로 실행한다 (필요한 패키지를 uv가 받는다). pip 설치나 가상환경 생성은 하지 않는다.
- 오래 걸리는 작업(10월 전체 받기 `sec_oct.py`, 벡터화 `embed.py`)은 백그라운드로 실행하고 진행 상황을 주기적으로 알려 준다. `embed.py`의 진행은 `jpm_kit/out/embed_progress.txt` 마지막 줄.
- Windows PowerShell 5.1은 한글 출력을 깨뜨릴 수 있다. 새로 만드는 스크립트의 출력 메시지는 영어로 쓴다.
- Windows에서 여러 명령을 `;`로 한 줄에 이으면 `uv`가 드물게 'unrecognized subcommand' 오류를 낸다. 그때는 명령을 하나씩 다시 실행한다.
- `python -c "..."` 는 쓰지 않는다(PowerShell이 큰따옴표를 깨뜨림). 짧은 확인 코드도 `jpm_kit/out/<이름>.py` 파일로 만들어 실행한다.

## 고치지 않는 파일
- `htmltext.py`(강사가 27,000건으로 검사한 변환기), `check_oct.py`(검증 기준), `data/oct_reference.csv`. 설명을 요청받으면 읽고 설명만 한다.

## DB
- 내 Azure PostgreSQL: `filings`(10월 공시 원문), `chunks`(검색 단위, `tsv`=키워드 색인, `emb`=벡터).
- 공용 상품 DB(읽기 전용, `.env`의 `SHARED_…`): `products`(강사가 10개월 공시로 만든 상품 표).
- 공시끼리 비교(특이한 공시, 새 상품 설명과 닮은 공시)는 `uv run jpm_kit/similar.py`(`--outliers N`, `--text "영어 설명"`, `--like <accession>`)를 먼저 쓴다. 공시 벡터는 `jpm_kit/out/doc_vectors.npz`에 저장된다.
- DB 연결은 `jpm_kit/kit_db.py`의 `connect()`(내 DB) / `connect("SHARED")`(공용)를 쓴다. `body`·`emb` 칸 전체를 출력하지 않는다(너무 길다).
- 표를 지우거나 바꾸기 전에는 사용자에게 먼저 묻는다.
- 숫자를 말할 때는 분모(공시 수 / 상품 수 / 값이 있는 상품 수)를 밝힌다. 빈칸은 0이 아니라 결측이다.
