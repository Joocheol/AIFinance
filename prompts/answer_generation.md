# 답변 생성 지침 (RAG 평가용)

> `aifinance` MCP 서버를 연결한 Claude Desktop에 붙여 넣는 프롬프트입니다. 질문 하나씩 실행하세요.

---

`aifinance` 도구를 써서 아래 질문에 답해줘.

**질문 ID**: `<id>`
**질문**: `<question>`
**채워야 할 key_values 키**: `<keys>` (숫자는 소수로: 13% → 0.13. 문자열은 DB 값 그대로)

## 답변 규칙
1. 숫자·집계는 `query_products`로 직접 계산한다. 추측하지 않는다.
2. 설명은 `search_filings`로 공시 원문을 찾아 근거로 쓴다. 검색어는 공시 용어(영어)로 쓴다.
3. 원문에서 확인하지 못한 내용은 "확인하지 못함"이라고 쓴다.
4. 인용(`citations`)은 실제 도구 결과에 나온 EDGAR 링크와, 그 공시에 **글자 그대로** 있는 영어 문장(200자 이내)만 쓴다.

## 출력
마지막에 아래 형식의 JSON을 `eval/answers/<id>.json`으로 저장해줘 (Code 탭이 아니면 JSON만 출력).

```json
{
  "id": "<id>",
  "answer": "한국어 답변 (3~8문장)",
  "key_values": {"<key>": 0.0},
  "citations": [{"cusip": "46661...", "url": "https://www.sec.gov/Archives/...", "quote": "원문 그대로의 문장"}],
  "tools_used": ["query_products", "search_filings"],
  "sql": ["실행한 SQL"]
}
```
