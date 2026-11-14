# 실습 키트 규칙 (Claude Code가 이 폴더에서 일할 때)

- 사용자에게는 **한국어로** 답한다. 표를 먼저 보이고 3~5줄로 해석한다.

## 비밀 정보
- `jpm_kit/.env` (또는 `.env.txt`) 에는 DB 비밀번호와 Azure OpenAI 키가 있다. **절대 열거나, 읽거나, 출력하거나, 내용을 요약하지 않는다.**
  `cat`, `type`, `Get-Content`, Read 도구, `grep` 등 어떤 방법으로도 열지 않는다. 스크립트가 알아서 읽는다.
- 값을 확인해야 하면 스크립트를 실행해 연결 성공/실패 메시지만 본다. 환경변수를 `echo`/`print` 하지 않는다.
- 사용자가 채팅에 비밀번호나 키를 붙여 넣으면, 쓰지 말고 `.env` 에 직접 적으라고 안내한다.

## 실행 방법
- 스크립트는 항상 `uv run jpm_kit/<스크립트>.py` 로 실행한다 (필요한 패키지를 uv가 받는다). pip 설치나 가상환경 생성은 하지 않는다.
- 순서: `01_load.py`(적재) → `04_embed.py`(벡터화, 오래 걸리므로 백그라운드) / `02_extract.py`(추출·채점) → `03_search_eval.py`(키워드 채점) → `05_eval_all.py`(세 방식 비교)
- 오래 걸리는 `04_embed.py` 는 백그라운드로 실행하고, 진행 상황은 `jpm_kit/out/embed_progress.txt` 의 마지막 줄로 확인한다.
- Windows에서는 PowerShell 5.1이 한글을 깨뜨릴 수 있다. 새로 만드는 스크립트의 출력 메시지는 영어로 쓴다.
- Windows PowerShell에서 여러 명령을 `;` 로 한 줄에 이으면 `uv` 가 드물게 'unrecognized subcommand' 오류를 낸다. 그때는 명령을 하나씩 다시 실행한다.

## DB
- 내 Azure PostgreSQL (pgvector). 표: `filings`(공시 원문), `chunks`(청크, tsv=키워드 색인, emb=벡터), `products`(상품 10,410개), `data_dictionary`(컬럼 설명), `my_products`(내가 추출한 표)
- SQL로 둘러볼 때는 `jpm_kit/out/` 에 짧은 `.py` 파일을 만들어 `import sys; sys.path.insert(0, 'jpm_kit'); import kit_common as kc` 후 `kc.connect()` 를 쓰고, `uv run --with "psycopg[binary]" python jpm_kit/out/<파일>.py` 로 실행한다.
  `python -c "..."` 는 쓰지 않는다: Windows PowerShell 5.1은 `-c` 안의 큰따옴표를 깨뜨린다(리허설에서 확인). `body`·`emb` 컬럼 전체를 출력하지 않는다(너무 길다).
- 표를 지우거나 바꾸기 전에는 사용자에게 먼저 묻는다. 실험은 새 표(`chunks_a` 등)에 한다.

## 데이터
- `data/filings_2026-09/` 9월 공시 1,890건(정규화 텍스트), `data/gold/` 정답 27건, `data/gold_texts/` 정답 문서 원문,
  `data/eval/retrieval_questions.jsonl` 검색 문항 20개, `data/products.csv` 상품 표
- 모두 공개 SEC 공시에서 만든 자료다. 회사·고객 자료를 이 폴더에 넣지 않는다.
- 숫자를 말할 때는 분모(문서 수 / 상품 수 / 값이 있는 상품 수)를 밝힌다.
