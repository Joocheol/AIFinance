# 답변 채점 지침 (Claude 채점자)

> 답변을 만든 대화와 **다른 대화**에서 사용합니다. 채점자가 답변자의 추론을 보지 못해야 공정합니다.

---

너는 구조화 상품 리서치 답변을 채점하는 검토자다. `eval/answer_questions.jsonl`에서 `type`이 `explanation`인 질문마다,
`eval/answers/<id>.json`의 답변을 아래 기준으로 채점해 `eval/judgments/<id>.json`으로 저장해줘.

## 채점 기준
1. **루브릭 충족**: 질문의 `rubric` 항목마다 답변이 그 내용을 담고 있으면 `true`. 표현이 달라도 뜻이 같으면 인정한다.
2. **근거 없는 주장**: 답변 문장 중 인용된 공시나 `search_filings` 결과로 뒷받침되지 않는 **사실 주장**을 찾아 목록으로 적는다.
   필요하면 `aifinance` 도구(또는 `uv run python -c "from aifinance import mcp_server as m; print(m.search_filings('...'))"`)로 직접 확인한다.
   일반 상식 수준의 연결 문장은 제외한다.
3. **점수**: `score = 충족한 루브릭 수 / 전체 루브릭 수`. 근거 없는 주장이 있으면 그대로 두고 따로 보고한다 (점수에서 빼지 않음).

## 출력 형식
```json
{
  "id": "<id>",
  "rubric": [{"item": "루브릭 문장", "met": true, "evidence": "답변 속 해당 구절"}],
  "score": 0.75,
  "unsupported_claims": [{"claim": "답변 속 문장", "why": "확인 결과"}],
  "comment": "한 줄 총평"
}
```
