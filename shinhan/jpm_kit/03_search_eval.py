# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]>=3.2"]
# ///
"""활동 5 — 키워드 검색(PostgreSQL 전문 검색)을 20문항으로 채점한다.

문항: data/eval/retrieval_questions.jsonl (공시 조건·위험에 관한 일반 질문 20개)
정답 판정: 검색된 청크 안에 그 문항의 정답 문구(relevant_phrases)가 들어 있으면 맞음
hit@5: 상위 5개 결과 안에 정답 청크가 하나라도 있는 문항의 비율

실행: uv run jpm_kit/03_search_eval.py
결과: 표 출력 + 문항별 결과 out/search_keyword.csv (놓친 문항을 Claude와 함께 살펴볼 때 사용)
"""

from __future__ import annotations

import csv
import time

import kit_common as kc

FIELDS = ["query", "query_paraphrase", "query_ko"]
qs = kc.load_questions()
conn = kc.connect()
cur = conn.cursor()
kc.OUT.mkdir(exist_ok=True)

detail, lat = [], []
for f in FIELDS:
    for q in qs:
        t0 = time.time()
        hits = kc.search_keyword(cur, q[f], k=5)
        lat.append(time.time() - t0)
        rank = next((i + 1 for i, (_, b) in enumerate(hits) if kc.is_hit(b, q)), None)
        detail.append({"field": f, "id": q["id"], "question": q[f], "hit5": rank is not None,
                       "rank": rank or "", "relevant_phrases": " / ".join(q["relevant_phrases"]),
                       "top1": (hits[0][1][:300] if hits else "(결과 없음)")})

print("키워드 검색 hit@5 (상위 5개 안에 정답 문단이 있는 문항 비율)\n")
print("| 질문 형태 | 키워드 검색 hit@5 |")
print("|---|---|")
for f in FIELDS:
    rows = [d for d in detail if d["field"] == f]
    print(f"| {kc.FIELDS[f]} | {sum(d['hit5'] for d in rows) / len(rows):.0%} ({sum(d['hit5'] for d in rows)}/{len(rows)}) |")
print(f"\n검색 1회 중앙값 {sorted(lat)[len(lat) // 2]:.2f}초")

with open(kc.OUT / "search_keyword.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(detail[0]))
    w.writeheader()
    w.writerows(detail)
miss = [d["id"] for d in detail if d["field"] == "query" and not d["hit5"]]
print(f"영어 원래 질문 중 놓친 문항: {', '.join(miss) or '없음'}  → 문항별 결과: jpm_kit/out/search_keyword.csv")
