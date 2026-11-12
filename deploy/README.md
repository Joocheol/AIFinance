# 내 MCP 서버를 Azure에 올리고 Claude에 연결하기

JP Morgan 구조화 노트 1만여 개 데이터(SEC 공시, 2025-10~2026-09)를 Claude가 직접 조회할 수 있는 서버를
**내 Azure 무료 계정**에 올리고, **Claude 커스텀 커넥터**로 연결합니다. 코드는 다루지 않습니다.

## 준비물
- Azure 무료 계정 (수업 전 과제로 생성 완료)
- Claude Pro 계정
- 인터넷 브라우저

## 1. 배포 (약 5분)

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FJoocheol%2FAIFinance%2Fcourse-dev%2Fdeploy%2Fazure%2Fazuredeploy.json)

1. 위 버튼을 누르고 Azure에 로그인합니다.
2. **리소스 그룹**: "새로 만들기" → `jpm-course`
3. **지역**: `Korea Central`
4. 나머지는 그대로 두고 **검토 + 만들기 → 만들기**
5. "배포가 완료되었습니다"가 나오면 왼쪽 **출력**에서 `mcpUrl` 값을 복사합니다.
   예: `https://jpm-mcp-ab12cd.koreacentral.azurecontainerapps.io/mcp`

> 리소스 공급자(Microsoft.App)는 배포할 때 자동으로 등록됩니다(2026-11-12 시험에서 확인). 그래도 `MissingSubscriptionRegistration` 오류로 실패하면: Azure 포털 → **구독** → 내 구독 → **리소스 공급자** →
> `Microsoft.App` 검색 → **등록** → 1~2분 뒤 다시 배포합니다.

## 2. Claude에 연결 (약 2분)

1. claude.ai (또는 Claude 앱) → **설정 → 커넥터** → **커스텀 커넥터 추가**
2. 이름: `JPM 424B2`, URL: 복사한 `mcpUrl` → **추가**
3. 새 대화를 열고 입력창의 도구 메뉴에서 `JPM 424B2`가 켜져 있는지 확인합니다.

## 3. 첫 질문

> JPM 424B2 데이터의 구조를 먼저 확인하고, 상품 유형별 상품 수와 평균 연 쿠폰을 표로 보여줘. 쿠폰 값이 비어 있는 상품 수도 함께 알려줘.

Claude가 `describe_database`, `query_products` 도구를 호출하는 과정이 화면에 보이면 성공입니다.
서버가 쉬고 있었다면 첫 질문은 깨어나느라 5~10초 더 걸립니다 (실측: 첫 응답 4.5초).

## 수업 후 정리 (중요)

- 계속 쓰지 않으려면: Azure 포털 → **리소스 그룹** → `jpm-course` → **리소스 그룹 삭제**
- 계속 쓰려면: **비용 관리 → 예산**에서 월 예산(예: $5)과 알림을 설정해 두세요.
  서버는 쓰지 않을 때 자동으로 꺼지도록(최소 0개) 설정되어 있습니다.

## 서버가 하는 일

| 도구 | 설명 |
|---|---|
| `describe_database` | 테이블·컬럼의 한국어 설명과 단위 |
| `query_products` | 읽기 전용 SQL (최대 50행) |
| `search_filings` | 공시 원문 검색 (의미 + 키워드) |
| `get_product` | CUSIP 하나의 조건과 SEC 원문 링크 |

데이터는 공개 SEC 공시에서 추출한 것이며, 상품 분류는 "계약조건 근거 규칙 분류(잠정)"입니다.
`price_value_gap_pct`(발행가격과 최초 추정가치의 차이)는 발행사 순이익이 아닙니다.

## 강사용: 이미지와 DB 갱신

```bash
# 1) Dropbox 수업 자료로 DB 만들기
uv run python -m aifinance.course_db --data <03_분석 압축 해제>/data --text <02_정규화텍스트 압축 해제>/raw/text
# 2) 릴리스 자산 교체 후 이미지 다시 빌드 (GitHub Actions: course-image)
gh release upload course-db-v1 data/shinhan_jpm.duckdb --clobber
gh workflow run course-image --ref course-dev
# 3) 로컬 시험
uv run python -m aifinance.course_server   # http://localhost:8000/mcp
```
