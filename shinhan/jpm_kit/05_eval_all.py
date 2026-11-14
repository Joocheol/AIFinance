# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]>=3.2", "httpx>=0.27"]
# ///
"""활동 6 — 같은 20문항을 키워드·벡터·하이브리드 세 방식 × 질문 형태 네 가지로 채점한다 (hit@5).

하이브리드 = 키워드 상위 50개와 벡터 상위 50개를 순위 융합(RRF): r위 청크에 가중치/(60+r) 점을 더해 합산.

실행: uv run jpm_kit/05_eval_all.py
      uv run jpm_kit/05_eval_all.py --table chunks_a         (실험 A·B: 다른 청크 표로)
      uv run jpm_kit/05_eval_all.py --weights 1,2            (실험 C: 키워드 1 : 벡터 2)
      uv run jpm_kit/05_eval_all.py --rewrite-file my_rewrites.jsonl  (실험 D: {"id":"r01","query":"..."} 줄마다)
결과: 표 출력 + out/search_all.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path

import kit_common as kc

ap = argparse.ArgumentParser()
ap.add_argument("--table", default="chunks")
ap.add_argument("--weights", default="1,1", help="하이브리드 가중치 키워드,벡터 (기본 1,1)")
ap.add_argument("--rewrite-file", help="실험 D: 내가 만든 검색어 파일(jsonl, id·query). '내 검색어' 행으로 채점")
args = ap.parse_args()
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", args.table):
    raise SystemExit("표 이름은 영문 소문자·숫자·밑줄만 쓸 수 있습니다.")
w_kw, w_vec = (float(x) for x in args.weights.split(","))

qs = kc.load_questions()
fields = dict(kc.FIELDS)
if args.rewrite_file:
    mine = {}
    for line in Path(args.rewrite_file).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            mine[d["id"]] = d["query"]
    for q in qs:
        q["query_mine"] = mine.get(q["id"], q["query_ko"])
    fields["query_mine"] = "내 검색어 (실험 D)"

conn = kc.connect()
cur = conn.cursor()
cur.execute(f"SELECT count(*), count(emb) FROM {args.table}")
n, n_emb = cur.fetchone()
if n_emb < n:
    print(f"주의: {args.table} 의 청크 {n:,}개 중 {n_emb:,}개만 벡터가 있습니다. 벡터·하이브리드 점수가 낮게 나올 수 있습니다.\n")

emb = kc.Embedder()
kc.OUT.mkdir(exist_ok=True)
detail, lat = [], {"keyword": [], "vector": [], "hybrid": []}
for f in fields:
    qvecs = emb([q[f] for q in qs])  # 질문 임베딩은 한 번에
    for q, qv in zip(qs, qvecs):
        t0 = time.time(); kw = kc.search_keyword(cur, q[f], k=50, table=args.table); t_kw = time.time() - t0
        t0 = time.time(); vec = kc.search_vector(cur, qv, k=50, table=args.table); t_vec = time.time() - t0
        hyb = kc.fuse([kw, vec], k=5, weights=[w_kw, w_vec])
        lat["keyword"].append(t_kw); lat["vector"].append(t_vec); lat["hybrid"].append(t_kw + t_vec)
        for mode, hits in (("keyword", kw[:5]), ("vector", vec[:5]), ("hybrid", hyb)):
            rank = next((i + 1 for i, (_, b) in enumerate(hits) if kc.is_hit(b, q)), None)
            detail.append({"field": f, "mode": mode, "id": q["id"], "question": q[f], "hit5": rank is not None, "rank": rank or ""})

print(f"hit@5 — 표 {args.table}, 문항 {len(qs)}개, 하이브리드 가중치 키워드 {w_kw:g} : 벡터 {w_vec:g}\n")
print("| 질문 형태 | 키워드 | 벡터 | 하이브리드 |")
print("|---|---|---|---|")
for f, label in fields.items():
    cells = []
    for mode in ("keyword", "vector", "hybrid"):
        rows = [d for d in detail if d["field"] == f and d["mode"] == mode]
        cells.append(f"{sum(d['hit5'] for d in rows) / len(rows):.0%}")
    print(f"| {label} | " + " | ".join(cells) + " |")
med = {k: sorted(v)[len(v) // 2] for k, v in lat.items()}
print(f"\n검색 1회 중앙값: 키워드 {med['keyword']:.2f}초, 벡터 {med['vector']:.2f}초, 하이브리드 {med['hybrid']:.2f}초"
      f" / 질문 임베딩 토큰 {emb.tokens:,}")

with open(kc.OUT / "search_all.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=list(detail[0]))
    w.writeheader()
    w.writerows(detail)
print("문항별 결과: jpm_kit/out/search_all.csv")
