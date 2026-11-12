# AIFinance

**AI로 SEC EDGAR 공시를 수집·DB화·RAG화하여 JP Morgan 구조화 상품을 해부하고, 그 결과로 신상품을 설계하는 금융권 실무자용 코스**

- **분석 대상**: JPMorgan Chase Financial Company LLC(CIK 1665650)가 발행하고 JPMorgan Chase & Co.가 보증하는 구조화 노트. 최근 1년 424B2 공시 약 2.2만 건.
- **AI 도구**: Claude Desktop 하나만 사용합니다. 별도 LLM API 키는 필요 없습니다.
  - Code 탭: 수집·파싱·DB 코드 작성 파트너
  - 로컬 MCP 서버: 상품 DB와 벡터 검색을 Claude에 연결해 근거 있는 분석 수행
- **임베딩·벡터 DB**: 로컬 오픈소스(무료)
- **교재**: Jupyter 노트북 (한국어 설명)

## 커리큘럼

| 모듈 | 주제 | 핵심 내용 | 상태 |
|---|---|---|---|
| 0 | [코스 소개와 환경 설정](notebooks/00_코스소개_환경설정.ipynb) | 코스 구조, 424B2 해부, 데이터 사전, Claude Desktop 사용법 | ✅ |
| 1 | [EDGAR 데이터 수집](notebooks/01_EDGAR_데이터_수집.ipynb) | submissions·전문검색 API, 표본 추출, 예비본·확정본 구분, 상품명 추출 | ✅ |
| 2 | [AI 정보 추출](notebooks/02_AI_정보추출.ipynb) | 스키마 정의, Claude로 정답셋 라벨링·검수, 규칙 기반 추출기 채점·오류 분석 | ✅ |
| 3 | 상품 DB 구축 | DuckDB 스키마, 예비본–확정본 병합, 품질 점검 | 예정 |
| 4 | 벡터화와 RAG | 청킹, 로컬 임베딩, Chroma, 하이브리드 검색, MCP 서버로 Claude 연결 | 예정 |
| 5 | RAG 평가 | 정답셋 구축, 검색·답변 정확도 측정 | 예정 |
| 6 | JPM 상품군 분석 | 상품 유형·기초자산·쿠폰·배리어 분포, 추정가치로 본 발행 마진, 시계열 추세 | 예정 |
| 7 | 신상품 설계 | 공백 분석, 아이디어 도출, 몬테카를로 프라이싱·백테스트, 텀시트 초안 | 예정 |
| 8 | 캡스톤 | 신상품 제안서 작성과 발표 | 예정 |

## 시작하기

[uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync                  # 가상환경 + 패키지 설치 (Python 3.12)
cp .env.example .env     # SEC_USER_AGENT 에 "이름 이메일" 입력
uv run jupyter lab
```

SEC는 자동화 요청에 연락처가 담긴 User-Agent와 초당 10건 이하의 요청 속도를 요구합니다([SEC 안내](https://www.sec.gov/os/accessing-edgar-data)). `src/aifinance/edgar.py`가 두 규칙을 모두 지킵니다.

## 폴더 구조

```
notebooks/          강의 노트북 (모듈별)
src/aifinance/      공용 코드 (EDGAR 클라이언트, 스키마, 추출기, 채점, 차트)
prompts/            Claude Desktop용 프롬프트 (정답셋 라벨링 지침 등)
gold/               Claude가 만들고 검수한 정답셋 (27건, dev/test 분할)
data/               수집 데이터 (git 제외)
  raw/              공시 원문 HTML
  interim/          목록·평문 parquet
```
