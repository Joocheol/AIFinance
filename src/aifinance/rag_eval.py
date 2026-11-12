"""모듈 5: RAG 평가.

1) 검색 평가: 질문마다 '정답 문단이라면 들어 있을 문구'로 관련성을 판정 → Hit@k, MRR.
   청크 번호가 아니라 내용으로 라벨링하므로 청크 크기·모델을 바꿔도 평가셋을 그대로 쓸 수 있다.
2) 답변 평가: Claude 답변(JSON)을 SQL 참값·원문과 자동 대조 + Claude 채점자의 루브릭 판정.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

from .config import DATA_DIR, PROJECT_ROOT
from .rag import search

EVAL_DIR = PROJECT_ROOT / "eval"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------ 검색 평가
def is_relevant(text: str, chunk_cusip: str | None, q: dict) -> bool:
    if q.get("cusip") and chunk_cusip != q["cusip"]:
        return False
    return any(p.lower() in text.lower() for p in q["relevant_phrases"])


def retrieval_eval(con: duckdb.DuckDBPyConnection, questions: list[dict], mode: str = "hybrid",
                   lang: str = "en", k: int = 10, auto_cusip: bool = True, field: str | None = None) -> pd.DataFrame:
    """field: 질문 문장을 고를 필드명(기본: lang 에 따라 query / query_ko). 예: 'query_paraphrase'."""
    rows = []
    for q in questions:
        query = q[field] if field else (q["query"] if lang == "en" else q["query_ko"])
        if q.get("cusip"):  # 상품 지정 질문: CUSIP 을 검색어에 넣는다 (청크 머리글의 CUSIP 을 키워드 검색이 잡도록)
            query = f"{query} CUSIP {q['cusip']}"
        hits = search(con, query, k=k, mode=mode, auto_cusip=auto_cusip)
        rel = [is_relevant(t, c, q) for t, c in zip(hits.text, hits.cusip)]
        first = next((i for i, r in enumerate(rel) if r), None)
        rows.append({"id": q["id"], "mode": mode, "lang": field or lang, "hit@1": bool(rel[:1] and rel[0]),
                     "hit@5": any(rel[:5]), "rr": 0.0 if first is None else 1 / (first + 1)})
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    return (results.groupby(["lang", "mode"])[["hit@1", "hit@5", "rr"]].mean()
            .rename(columns={"rr": "MRR"}).round(3))


# ------------------------------------------------------------------ 답변 평가
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def truth_values(con: duckdb.DuckDBPyConnection, q: dict) -> dict:
    row = con.execute(q["truth_sql"]).df().iloc[0].to_dict()
    return {k: row[col] for k, col in q["keys"].items()}


def check_values(answer: dict, truth: dict, tol: float) -> dict[str, bool]:
    got = answer.get("key_values", {})
    out = {}
    for k, t in truth.items():
        v = got.get(k)
        if isinstance(t, str):
            out[k] = isinstance(v, str) and v.strip().lower() == t.lower()
        else:
            try:
                out[k] = abs(float(v) - float(t)) <= tol + 1e-9
            except (TypeError, ValueError):
                out[k] = False
    return out


def check_citations(answer: dict, con: duckdb.DuckDBPyConnection, text_dir: Path = DATA_DIR / "text") -> pd.DataFrame:
    """인용마다: 링크가 DB 에 있는 공시인가, 인용문이 그 공시 원문에 그대로 있는가."""
    url_to_acc = dict(con.execute("SELECT url, accession_number FROM documents").fetchall())
    rows = []
    for c in answer.get("citations", []):
        acc = url_to_acc.get(c.get("url", ""))
        quote = c.get("quote") or ""
        found = None
        if acc and quote and (text_dir / f"{acc}.txt").exists():
            found = _norm(quote) in _norm((text_dir / f"{acc}.txt").read_text())
        rows.append({"url_known": acc is not None, "quote": quote[:80], "quote_found": found})
    return pd.DataFrame(rows, columns=["url_known", "quote", "quote_found"])
