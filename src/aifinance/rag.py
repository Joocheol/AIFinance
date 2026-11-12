"""모듈 4: 공시 원문 벡터화와 하이브리드 검색 (DuckDB 하나로).

- 청킹: 문단 단위로 묶되, 여러 문서에 반복되는 공통 문구(boilerplate)는 따로 한 번만 색인
- 임베딩: fastembed 다국어 모델 (로컬, 무료, torch 불필요) → 한국어 질문으로 영어 공시 검색
- 검색: 벡터 유사도 + BM25 키워드 → 순위 융합(RRF)
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from functools import lru_cache

import duckdb
import numpy as np
import pandas as pd

# 기본 모델: 영어 전용 소형 모델. MCP 구조에서는 Claude 가 질문을 영어 검색어로 바꿔 호출하므로 충분하고 빠르다.
# 한국어로 직접 검색하려면 다국어 모델(MULTILINGUAL_MODEL)을 쓴다. 대신 색인이 3~10배 느리다.
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
MULTILINGUAL_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
MAX_CHARS = 1200  # 청크 최대 길이(문자)


# ------------------------------------------------------------------ 청킹
def paragraphs(text: str) -> list[str]:
    """문단 단위로 나눈다. 줄바꿈이 거의 없는 한 줄짜리 텍스트(Dropbox 정규화 텍스트 등)는 문장 단위로 나눈다."""
    if text.count("\n") < 5 and len(text) > 5000:
        units = re.split(r"(?<=[.;])\s+(?=[A-Z●•“\"(])", re.sub(r"\s+", " ", text))
        return [u.strip() for u in units if len(u.strip()) >= 20]
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if len(p) >= 40]  # 페이지 번호·머리글 같은 짧은 조각 제거


def _key(p: str) -> str:
    # 페이지 표기('PS-3')만 지우고 해시. 숫자까지 지우면 'Trigger Value: 50.00%' 같은
    # 상품별 조건 줄이 모두 같은 문단으로 묶여 공통 문구로 잘못 분류된다.
    return hashlib.md5(re.sub(r"\b(?:PS|US|TS)-\s?\d+\b", "", p.lower()).encode()).hexdigest()


def find_boilerplate(texts: list[str], min_share: float = 0.05, min_docs: int = 5) -> set[str]:
    """여러 문서에 반복 등장하는 문단의 키 집합."""
    counts = Counter(k for t in texts for k in {_key(p) for p in paragraphs(t)})
    threshold = max(min_docs, int(len(texts) * min_share))
    return {k for k, n in counts.items() if n >= threshold}


def pack(paras: list[str], max_chars: int = MAX_CHARS) -> list[str]:
    """문단을 max_chars 이내로 이어 붙인다. 긴 문단은 문장 경계에서 자른다."""
    chunks, cur = [], ""
    for p in paras:
        pieces = [p] if len(p) <= max_chars else re.split(r"(?<=[.;])\s+", p)
        for piece in pieces:
            if cur and len(cur) + len(piece) + 1 > max_chars:
                chunks.append(cur)
                cur = ""
            cur = f"{cur} {piece}".strip() if cur else piece[:max_chars * 2]
    if cur:
        chunks.append(cur)
    return chunks


def make_chunks(docs: pd.DataFrame, boilerplate: set[str], pack_boilerplate: bool = False) -> pd.DataFrame:
    """docs: accession_number, cusip, product_name, doc_status, filing_date, text.

    청크 앞에 상품 정보 머리글을 붙인다(contextual header). 청크만 떼어 봐도 어느 상품 얘기인지 알 수 있어
    검색 품질이 좋아지고, LLM 이 답할 때 출처를 밝히기 쉽다.
    """
    rows, seen_bp = [], {}
    for d in docs.itertuples():
        specific, bp = [], []
        for p in paragraphs(d.text):
            (bp if _key(p) in boilerplate else specific).append(p)
        header = f"[{d.product_name or '상품명 미상'} | CUSIP {d.cusip or '-'} | {d.doc_status} | {str(d.filing_date)[:10]}]"
        for i, c in enumerate(pack(specific)):
            rows.append({"accession_number": d.accession_number, "cusip": d.cusip, "seq": i,
                         "is_boilerplate": False, "text": f"{header}\n{c}"})
        for p in bp:  # 공통 문구는 처음 본 문서 기준으로 한 번만
            seen_bp.setdefault(_key(p), (d.accession_number, p))
    if pack_boilerplate:  # 문장 단위 공통 문구는 처음 등장한 순서대로 이어 붙여 청크로 만든다
        by_acc: dict[str, list[str]] = {}
        for acc, p in seen_bp.values():
            by_acc.setdefault(acc, []).append(p)
        bp_items = [(acc, c) for acc, ps in by_acc.items() for c in pack(ps)]
    else:
        bp_items = list(seen_bp.values())
    for i, (acc, p) in enumerate(bp_items):
        rows.append({"accession_number": acc, "cusip": None, "seq": i, "is_boilerplate": True,
                     "text": f"[공통 문구 | JPMorgan Chase Financial 구조화 노트]\n{p}"})
    out = pd.DataFrame(rows)
    out.insert(0, "chunk_id", range(len(out)))
    return out


# ------------------------------------------------------------------ 임베딩
@lru_cache(maxsize=2)
def _model(name: str):
    import os

    from fastembed import TextEmbedding

    # 컨테이너에서는 이미지에 미리 받아 둔 모델 폴더(FASTEMBED_CACHE_PATH)를 쓴다
    return TextEmbedding(model_name=name, cache_dir=os.getenv("FASTEMBED_CACHE_PATH"))


def embed(texts: list[str], model: str = DEFAULT_MODEL, batch_size: int = 64) -> np.ndarray:
    vecs = np.array(list(_model(model).embed(texts, batch_size=batch_size)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)  # 정규화 → 내적 = 코사인 유사도


# ------------------------------------------------------------------ 색인
def build_index(con: duckdb.DuckDBPyConnection, chunks: pd.DataFrame, model: str = DEFAULT_MODEL,
                show_progress: bool = True) -> None:
    texts = chunks.text.tolist()
    if show_progress:
        from tqdm import tqdm

        vecs = np.vstack([embed(texts[i:i + 512], model) for i in tqdm(range(0, len(texts), 512), desc="임베딩")])
    else:
        vecs = embed(texts, model)
    dim = vecs.shape[1]
    df = chunks.assign(embedding=list(vecs))
    con.execute("DROP TABLE IF EXISTS chunks")
    con.execute(f"""CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, accession_number VARCHAR, cusip VARCHAR,
                    seq INTEGER, is_boilerplate BOOLEAN, text VARCHAR, embedding FLOAT[{dim}])""")
    con.register("_c", df)
    con.execute("INSERT INTO chunks SELECT chunk_id, accession_number, cusip, seq, is_boilerplate, text, embedding::FLOAT[%d] FROM _c" % dim)
    con.unregister("_c")
    con.execute("CREATE OR REPLACE TABLE rag_meta AS SELECT ? AS model, ? AS dim, now()::TIMESTAMP AS built_at", [model, dim])
    con.execute("INSTALL fts; LOAD fts")
    con.execute("PRAGMA create_fts_index('chunks', 'chunk_id', 'text', overwrite=1)")


# ------------------------------------------------------------------ 검색
CUSIP_IN_QUERY = re.compile(r"\b[0-9]{3}[0-9A-Z]{5}[0-9]\b")


def search(con: duckdb.DuckDBPyConnection, query: str, k: int = 8, mode: str = "hybrid",
           where: str | None = None, include_boilerplate: bool = True, auto_cusip: bool = True) -> pd.DataFrame:
    """mode: 'vector' | 'keyword' | 'hybrid'.  where: products 뷰 컬럼에 대한 SQL 조건 (예: "p.product_family = 'digital'").

    auto_cusip: 검색어에 CUSIP 이 있으면 그 상품의 청크로 범위를 좁힌다. 벡터 검색은 CUSIP 같은 식별자를
    의미로 이해하지 못해 다른 상품의 비슷한 문단을 가져오기 때문이다 (모듈 5 평가에서 발견).
    """
    model, dim = con.execute("SELECT model, dim FROM rag_meta").fetchall()[0]
    con.execute("LOAD fts")
    filters = []
    if auto_cusip and (m := CUSIP_IN_QUERY.search(query)):
        filters.append(f"c.cusip = '{m.group(0)}'")
    if not include_boilerplate:
        filters.append("NOT c.is_boilerplate")
    if where:
        filters.append(f"({where})")
    cond = " AND ".join(filters) or "TRUE"
    base = f"FROM chunks c LEFT JOIN products p ON p.cusip = c.cusip WHERE {cond}"
    pool = max(k * 5, 50)

    ranks = {}
    if mode in ("vector", "hybrid"):
        qv = embed([query], model)[0].tolist()
        ranks["vector"] = con.execute(
            f"SELECT c.chunk_id, array_inner_product(c.embedding, ?::FLOAT[{dim}]) AS score {base} ORDER BY score DESC LIMIT {pool}",
            [qv]).df()
    if mode in ("keyword", "hybrid"):
        ranks["keyword"] = con.execute(
            f"SELECT * FROM (SELECT c.chunk_id, fts_main_chunks.match_bm25(c.chunk_id, ?) AS score {base}) "
            f"WHERE score IS NOT NULL ORDER BY score DESC LIMIT {pool}", [query]).df()

    # Reciprocal Rank Fusion: 각 방식의 순위 r 에 1/(60+r) 점수를 주고 합산. 점수 척도가 달라도 합칠 수 있다.
    fused: dict[int, float] = {}
    for name, df in ranks.items():
        for r, cid in enumerate(df.chunk_id):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + r)
    top = sorted(fused, key=fused.get, reverse=True)[: k * 4]
    if not top:
        return pd.DataFrame(columns=["chunk_id", "rrf", "cusip", "accession_number", "product_family", "text"])
    out = con.execute(
        "SELECT c.chunk_id, c.cusip, c.accession_number, c.is_boilerplate, p.product_family, c.text "
        f"FROM chunks c LEFT JOIN products p ON p.cusip = c.cusip WHERE c.chunk_id IN ({','.join(map(str, top))})").df()
    out["rrf"] = out.chunk_id.map(fused)
    out = out.sort_values("rrf", ascending=False)
    # 머리글만 다르고 본문이 같은 청크(여러 상품에 같은 문단)는 하나만 남긴다
    body = out.text.str.split("\n", n=1).str[-1].str[:300]
    return out[~body.duplicated()].head(k).reset_index(drop=True)


# ------------------------------------------------------------------ 한 번에
def index_database(con: duckdb.DuckDBPyConnection, texts: dict[str, str] | pd.Series, model: str = DEFAULT_MODEL,
                   statuses: tuple[str, ...] = ("final",)) -> pd.DataFrame:
    """DB 의 terms·documents 메타데이터와 원문(texts: 접수번호 → 평문)으로 청크를 만들고 색인한다."""
    meta = con.execute(f"""
        SELECT t.accession_number, t.cusip, t.product_name, t.doc_status, d.filing_date
        FROM terms t JOIN documents d USING (accession_number)
        WHERE t.doc_status IN ({','.join("'" + s + "'" for s in statuses)})""").df()
    meta["text"] = meta.accession_number.map(texts)
    meta = meta.dropna(subset=["text"])
    boiler = find_boilerplate(meta.text.tolist())
    chunks = make_chunks(meta, boiler)
    build_index(con, chunks, model)
    return chunks
