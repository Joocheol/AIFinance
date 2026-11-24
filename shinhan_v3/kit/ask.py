# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]", "httpx"]
# ///
"""내 DB에서 공시 문단 찾기: 키워드, 벡터(뜻), 둘을 합친 하이브리드.

    uv run jpm_kit/ask.py "6.0% per annum daily deduction"                 # 세 방식 나란히 상위 5개
    uv run jpm_kit/ask.py "지수에서 매일 빠지는 비용" --mode vector
    uv run jpm_kit/ask.py "barrier" --accession 0001213900-26-1xxxxx       # 공시 한 건 안에서만
    uv run jpm_kit/ask.py "..." --sql                                       # 실행하는 SQL 도 보여 주기

키워드: PostgreSQL 전문 검색 (같은 단어가 있어야 찾음, ts_rank_cd 순)
벡터:   질문을 같은 모델로 벡터로 바꾼 뒤 코사인 거리가 가까운 청크 (뜻이 가까우면 단어가 달라도 찾음)
하이브리드: 두 목록의 순위를 합침 (RRF: 각 목록에서 r위면 1/(60+r) 점)
"""

from __future__ import annotations

import argparse
import textwrap

import kit_db

KW_SQL = """select chunk_id, accession, body from chunks, websearch_to_tsquery('english', %(q)s) q
where tsv @@ q {acc} order by ts_rank_cd(tsv, q) desc, chunk_id limit %(k)s"""
VEC_SQL = """select chunk_id, accession, body from chunks
where emb is not null {acc} order by emb <=> %(v)s::vector limit %(k)s"""


def run(cur, sql, params, show):
    if show:
        print(textwrap.indent(sql.strip(), "    SQL> "))
    cur.execute(sql, params)
    return cur.fetchall()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--mode", choices=["all", "keyword", "vector", "hybrid"], default="all")
    ap.add_argument("--accession")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--sql", action="store_true")
    a = ap.parse_args()
    cur = kit_db.connect().cursor()
    acc = "and accession = %(acc)s" if a.accession else ""
    p = {"q": a.query, "k": 50, "acc": a.accession}
    res = {}
    if a.mode in ("all", "keyword", "hybrid"):
        res["키워드"] = run(cur, KW_SQL.format(acc=acc), p, a.sql)
    if a.mode in ("all", "vector", "hybrid"):
        p["v"] = kit_db.vec(kit_db.Embedder()([a.query])[0])
        cur.execute("set hnsw.ef_search = 400")  # 후보를 넉넉히: 100이면 6만 청크에서 진짜 1위를 놓친 적이 있다 (리허설)
        res["벡터"] = run(cur, VEC_SQL.format(acc=acc), p, a.sql)
    if a.mode in ("all", "hybrid"):
        score = {}
        for lst in (res.get("키워드", []), res.get("벡터", [])):
            for r, row in enumerate(lst):
                score.setdefault(row[0], [0.0, row])[0] += 1 / (60 + r + 1)
        res["하이브리드"] = [s[1] for s in sorted(score.values(), key=lambda s: -s[0])]
    for name, rows in res.items():
        if a.mode not in ("all", {"키워드": "keyword", "벡터": "vector", "하이브리드": "hybrid"}[name]):
            continue
        print(f"\n== {name} (상위 {a.k})")
        if not rows:
            print("  (찾은 것 없음)")
        for i, (cid, accn, body) in enumerate(rows[: a.k], 1):
            print(f"  {i}. [{accn} #{cid}] {' '.join(body.split())[:220]}")


if __name__ == "__main__":
    main()
