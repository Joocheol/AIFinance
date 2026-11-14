# 실습 키트 `jpm_kit` — 내 Azure DB에 공시를 넣고, 검색 품질을 재고, 벡터로 개선한다

Claude Desktop **Code 탭**에서 폴더 `jpm-class` 를 열고, Claude에게 아래 스크립트를 설명·실행하게 합니다.
모든 스크립트는 `uv run jpm_kit/<이름>.py` 로 실행합니다 (필요한 패키지는 uv가 자동으로 받습니다).

## 준비: `.env`
1. 이 폴더의 `.env.example` 을 복사해 이름을 `.env` 로 바꿉니다.
2. 메모장(Mac은 텍스트 편집기)으로 열어 배포 출력값 네 칸(`PGHOST`, `PGPASSWORD`, `AOAI_ENDPOINT`, `AOAI_KEY`)을 채웁니다.
3. `.env` 는 비밀 파일입니다. 채팅에 붙여 넣거나 Claude에게 보여 달라고 하지 않습니다.

## 스크립트

| 순서 | 스크립트 | 하는 일 | 시간(참고) |
|---|---|---|---|
| 활동 3 | `01_load.py` | 9월 공시 1,890건 → `filings`, 청크 약 4.8만 개 → `chunks`(키워드 색인 포함), 상품 표 10,410개 → `products`, 컬럼 설명 → `data_dictionary` | 약 1분 |
| 활동 3 | `04_embed.py` | 청크를 내 Azure OpenAI로 벡터화 → `chunks.emb`, 끝나면 벡터 색인(HNSW). **백그라운드로 실행**, 중간에 멈춰도 다시 실행하면 이어서 | 약 15분 (분당 100만 토큰 기준) |
| 활동 4 | `02_extract.py` | 규칙으로 상품 조건 추출 → 정답 27건과 필드별 채점 → `my_products`. `--score-only` 는 채점만 | 1~2분 |
| 활동 5 | `03_search_eval.py` | 키워드 검색을 20문항 × 질문 형태 3가지로 채점 (hit@5) | 1분 |
| 활동 6 | `05_eval_all.py` | 키워드·벡터·하이브리드 × 질문 형태 4가지 채점. 실험 옵션 `--table`, `--weights`, `--rewrite-file` | 2분 |

추출 규칙은 `kit_extract.py` 의 `extract()`, 청크 나누기와 검색은 `kit_common.py` 에 있습니다. 활동 4·6에서 Claude와 함께 고칩니다.

## 활동 6 조별 실험
- A. 청크 머리글: `uv run jpm_kit/01_load.py --table chunks_a --header` → `04_embed.py --table chunks_a` → `05_eval_all.py --table chunks_a`
- B. 청크 크기: `01_load.py --table chunks_b --max-chars 600` (또는 2400) → 같은 순서
- C. 하이브리드 비율: `05_eval_all.py --weights 1,2` (키워드 1 : 벡터 2) 등
- D. 질문 다듬기: 한국어 질문을 공시 용어로 바꾼 검색어 파일을 만들고 `05_eval_all.py --rewrite-file my_rewrites.jsonl`

A·B는 청크를 새로 만들어 다시 벡터화하므로 시간과 비용이 듭니다 (리허설: A 약 17분, B(600자, 청크 2배) 약 22분 중 벡터 색인만 13분, 임베딩 각각 약 $0.21~0.22). 실험 표 하나마다 DB가 0.9~1.3GB 늘어납니다.

## 막혔을 때
- `DB 연결 실패 … pg_hba.conf` / timeout: DB 방화벽이 지금 IP를 막고 있습니다. 포털 → `jpm-pg-…` → **네트워킹** → **현재 클라이언트 IP 주소 추가** → 저장.
- `password authentication failed`: `.env` 의 `PGPASSWORD` 를 배포 때 정한 비밀번호로 고칩니다.
- 벡터화 중 "한도 대기"가 늘어남: 정상입니다. 분당 한도에 맞춰 자동으로 기다립니다.
- 결과 파일은 `jpm_kit/out/` 에 저장됩니다.

## 데이터 (`data/`)
| 경로 | 내용 |
|---|---|
| `filings_2026-09/*.txt` | 2026년 9월 제출 JPM 424B2 1,890건의 정규화 텍스트 (파일 이름 = accession) |
| `gold/*.json`, `gold_texts/*.txt` | 사람이 원문과 대조해 만든 정답 27건과 그 원문 |
| `eval/retrieval_questions.jsonl` | 검색 문항 20개 (영어, 바꿔 말한 영어, 한국어, 영어 검색어, 정답 문구) |
| `products.csv`, `products_schema.json` | 12개월 상품 표 10,410행과 컬럼 형식 |

모두 공개된 SEC 공시에서 만든 자료입니다. 원문: `https://www.sec.gov/Archives/edgar/data/19617/<accession에서 - 를 뺀 것>/`
