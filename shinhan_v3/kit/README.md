# AI Finance 1 실습 키트 (jpm_kit)

`문서/jpm-class/jpm_kit/` 에 있어야 합니다 (`문서/jpm-class/jpm_kit/README.md` = 이 파일).
VS Code로 `jpm-class` 폴더를 열고, Claude Code 패널과 터미널에서 씁니다. 실행은 모두 `uv run jpm_kit/<파일>.py`.

## 먼저
1. `.env.example`을 복사해 이름을 `.env`로 바꾸고, 메모장으로 열어 `SEC_CONTACT` 한 줄만 채웁니다 (나머지는 수업 중에).
2. `.env`는 비밀 파일입니다. 채팅에 붙여 넣거나 Claude에게 열어 보라고 하지 않습니다.

## 실습별 파일

| 실습 | 파일 | 하는 일 |
|---|---|---|
| 1. SEC 10월 수집 | (`sec_oct.py`) | **수업 중에 Claude와 함께 만듭니다** (키트에 없음) |
| | `check_oct.py` | 내가 받은 10월 공시를 강사 기준(`data/oct_reference.csv`)과 대조 |
| 2. HTML → 텍스트 | `htmltext.py` | 변환기 (강사 제공, 고치지 않음) |
| | `to_text.py` | `sec_oct/html` → `sec_oct/text` 변환 + 글자 보존 검사. `--show <accession>` 한 건 보기 |
| 3. Azure DB | `load_text.py` | 10월 텍스트를 내 DB의 `filings`, `chunks` 표로 |
| | `shared_products.py` | 강사의 공용 상품 DB 읽기, 내 공시와 이어 보기 |
| 4. 임베딩·질의 | `embed.py` | 청크를 내 Azure OpenAI로 벡터화 (`--try 3`: 3개만 시험) |
| | `emb_1_words.py` | 단어 벡터: 가까운 단어, king − man + woman, 그림 2장 (`out/`) |
| | `emb_2_sentences.py` | 문장 임베딩: 문맥, 한국어–영어, 숫자에 약한 점 |
| | `ask.py` | 키워드·벡터·하이브리드 검색 나란히 (`--sql`로 SQL 보기) |
| 공용 | `kit_db.py` | `.env` 읽기, DB 연결, 임베딩 호출 |
| | `CLAUDE.md` | Claude Code가 이 폴더에서 지킬 규칙 (`.env` 열지 않기 등) |

## 만들어지는 폴더
- `sec_oct/html`, `sec_oct/text`: 내가 받은 10월 원문과 텍스트
- `out/`: 그림, 진행 기록 등

모두 공개 SEC 공시에서 만든 자료입니다. 회사·고객 자료를 이 폴더에 넣지 않습니다.
