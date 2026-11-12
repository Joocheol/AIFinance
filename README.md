# AIFinance

**AI로 SEC EDGAR 공시를 수집·DB화·RAG화하여 JP Morgan 구조화 상품을 해부하고, 그 결과로 신상품을 설계하는 금융권 실무자용 코스**

- **분석 대상**: JPMorgan Chase Financial Company LLC(CIK 1665650)가 발행하고 JPMorgan Chase & Co.가 보증하는 구조화 노트. 최근 1년 424B2 공시 약 2.2만 건.
- **AI 도구**: Claude Desktop 하나만 사용합니다. 별도 LLM API 키는 필요 없습니다.
  - Code 탭: 수집·파싱·DB 코드 작성 파트너
  - 로컬 MCP 서버: 상품 DB와 벡터 검색을 Claude에 연결해 근거 있는 분석 수행
- **임베딩·검색**: 로컬 임베딩(fastembed) + DuckDB 하이브리드 검색(벡터 + BM25). 별도 벡터 DB 없음
- **교재**: Jupyter 노트북 (한국어 설명)

## 커리큘럼

| 모듈 | 주제 | 핵심 내용 | 상태 |
|---|---|---|---|
| 0 | [코스 소개와 환경 설정](notebooks/00_코스소개_환경설정.ipynb) | 코스 구조, 424B2 해부, 데이터 사전, Claude Desktop 사용법 | ✅ |
| 1 | [EDGAR 데이터 수집](notebooks/01_EDGAR_데이터_수집.ipynb) | submissions·전문검색 API, 표본 추출, 예비본·확정본 구분, 상품명 추출 | ✅ |
| 2 | [AI 정보 추출](notebooks/02_AI_정보추출.ipynb) | 스키마 정의, Claude로 정답셋 라벨링·검수, 규칙 기반 추출기 채점·오류 분석 | ✅ |
| 3 | [상품 DB 구축](notebooks/03_상품_DB_구축.ipynb) | CUSIP으로 공시 이력 연결, DuckDB 스키마, 품질 점검 규칙, 전체 기간 파이프라인 | ✅ |
| 4 | [벡터화·RAG·MCP](notebooks/04_벡터화_RAG_MCP.ipynb) | 공통 문구 분리 청킹, 로컬 임베딩, DuckDB 하이브리드 검색, RAG vs SQL, MCP 서버로 Claude Desktop 연결 | ✅ |
| 5 | [RAG 평가](notebooks/05_RAG_평가.ipynb) | 내용 기반 검색 평가셋, 라벨 누출과 쉬운 말 질문, Claude 검색어 재작성, 답변의 숫자·인용·루브릭 채점 | ✅ |
| 6 | [JPM 상품군 분석](notebooks/06_JPM_상품군_분석.ipynb) | 상품군·판매 채널·기초자산·오토콜 조건, 추정가치로 본 마진, 교란 통제, 경쟁사 분석 메모와 신상품 가설 | ✅ |
| 7 | 신상품 설계 | 공백 분석, 아이디어 도출, 몬테카를로 프라이싱·백테스트, 텀시트 초안 | 예정 |
| 8 | 캡스톤 | 신상품 제안서 작성과 발표 | 예정 |

## 시작하기

[uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync                  # 가상환경 + 패키지 설치 (Python 3.12)
cp .env.example .env     # SEC_USER_AGENT 에 "이름 이메일" 입력
uv run jupyter lab
```

전체 기간 데이터로 DB를 만들려면 (모듈 6에서 사용, 30~40분):

```bash
uv run python -m aifinance.pipeline --start 2026-07-29 --end 2026-11-10
```

SEC는 자동화 요청에 연락처가 담긴 User-Agent와 초당 10건 이하의 요청 속도를 요구합니다([SEC 안내](https://www.sec.gov/os/accessing-edgar-data)). `src/aifinance/edgar.py`가 두 규칙을 모두 지킵니다.

## Claude Desktop 연결 (모듈 4)

- **Code 탭**: 이 폴더를 열면 `.mcp.json`의 `aifinance` 서버를 쓸지 묻습니다.
- **일반 채팅**: 노트북 04의 5-2 셀이 `claude_desktop_config.json`에 넣을 설정을 만들어 줍니다.

도구: `describe_database`, `query_products`(읽기 전용 SQL), `search_filings`(공시 원문 하이브리드 검색), `get_product`(CUSIP별 조건·이력)

## 폴더 구조

```
notebooks/          강의 노트북 (모듈별)
src/aifinance/      공용 코드 (EDGAR 클라이언트, 스키마, 추출기, 채점, 차트)
prompts/            Claude Desktop용 프롬프트 (라벨링·답변 생성·채점 지침)
.mcp.json           Code 탭에서 이 폴더를 열면 쓸 수 있는 MCP 서버 설정
gold/               Claude가 만들고 검수한 추출 정답셋 (27건, dev/test 분할)
eval/               RAG 평가셋, 예시 답변(answers/)과 채점 결과(judgments/)
data/               수집 데이터 (git 제외)
  raw/              공시 원문 HTML
  interim/          목록·평문 parquet
```
