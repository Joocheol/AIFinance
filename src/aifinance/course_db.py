"""신한은행 수업용 12개월 DB (Dropbox 수업 자료 기준).

    uv run python -m aifinance.course_db --data <압축 푼 03_분석 폴더>/data --text <정규화 텍스트 폴더>/raw/text

- 상품 표는 Dropbox 의 products_in_period.csv(10,410개, 예정 발행일 2025-10-01~2026-09-30)를 그대로 쓴다.
  수업 Excel 과 같은 분모·같은 숫자를 Claude 가 보게 하기 위해서다.
- 판매 채널(channel)만 원문에서 판별해 덧붙인다 (모듈 6의 규칙).
- 공시 원문 검색 색인은 확정 공시의 상품별 문단(앞부분) + 공통 문구로 만든다.
  임베딩은 정적 모델 potion-retrieval-32M — 모듈 5 평가셋 기준 bge-small 과 비슷한 품질에 150배 빠르고 메모리 0.5GB.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd
from tqdm import tqdm

from .config import DATA_DIR
from .db import channel
from .rag import build_index, find_boilerplate, make_chunks

COURSE_DB = DATA_DIR / "shinhan_jpm.duckdb"
COURSE_MODEL = "minishlab/potion-retrieval-32M"  # 영어 검색 전용 정적 모델, 메모리 0.5GB (다국어 128M 은 1.7GB 로 무료 사양 1GB 초과)
CHUNKS_PER_DOC = 8  # 문서당 상품별 청크 상한 (표지·Key Terms 가 앞부분에 있음)

PRODUCT_COLUMNS = [
    "product_key", "cusip", "isin", "accession", "filing_date", "title", "issuer", "guarantor",
    "pricing_date", "trade_date", "issue_date", "maturity_date", "tenor_years", "currency",
    "principal", "public_offering_amount", "issue_price_per_1000", "estimated_value_per_1000", "price_value_gap_pct",
    "product_type", "contract_class", "underliers", "tickers", "underlier_structure",
    "coupon_type", "coupon_annual_pct", "coupon_frequency", "memory", "autocall", "issuer_call",
    "coupon_barrier_pct", "principal_barrier_pct", "buffer_pct", "cap_pct", "participation",
    "principal_protection", "barrier_observation", "coupon_observation",
    "multiple_products_flag", "split_rule", "confidence", "human_review_status", "missing_fields",
    "related_accessions", "primary_document_url",
]
FILING_COLUMNS = ["accession", "filing_date", "month", "form", "document_class", "issuer", "guarantor",
                  "registrant_ciks", "primary_document_url"]


def build(data_dir: Path, text_dir: Path, db_path: Path = COURSE_DB, chunks_per_doc: int = CHUNKS_PER_DOC) -> None:
    products = pd.read_csv(data_dir / "products_in_period.csv", low_memory=False, dtype={"cusip": str, "isin": str})
    products = products[PRODUCT_COLUMNS].copy()
    filings = pd.read_csv(data_dir / "filings_with_status.csv", low_memory=False)[FILING_COLUMNS]
    dictionary = pd.read_csv(data_dir / "data_dictionary.csv")

    texts = {a: (text_dir / f"{a}.txt").read_text() for a in tqdm(products.accession.unique(), desc="원문 읽기")
             if (text_dir / f"{a}.txt").exists()}
    products["channel"] = products.accession.map(lambda a: channel(texts.get(a)))
    products["product_family"] = products.product_type  # rag.search 와 호환
    for c in ["filing_date", "pricing_date", "trade_date", "issue_date", "maturity_date"]:
        products[c] = pd.to_datetime(products[c], errors="coerce").dt.date
    filings["filing_date"] = pd.to_datetime(filings.filing_date, errors="coerce").dt.date

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    for name, df in [("products", products), ("filings", filings), ("data_dictionary", dictionary)]:
        con.register("_df", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _df")
        con.unregister("_df")
    # search_filings 가 링크를 찾는 documents 테이블 (공시 1건 = 1행)
    con.execute("CREATE TABLE documents AS SELECT accession AS accession_number, filing_date, form, document_class, "
                "primary_document_url AS url FROM filings")

    # 검색 색인: 상품 공시(확정본) 원문
    by_doc = products.groupby("accession").agg(cusips=("cusip", lambda s: sorted(set(s.dropna()))),
                                               title=("title", "first"), filing_date=("filing_date", "first"))
    meta = pd.DataFrame({
        "accession_number": by_doc.index,
        "cusip": [c[0] if len(c) == 1 else None for c in by_doc.cusips],  # 노트 여러 종이 실린 공시는 CUSIP 을 비움
        "product_name": [t if len(c) == 1 else f"{t} 외 {len(c) - 1}종 (CUSIP {', '.join(c)})"
                         for t, c in zip(by_doc.title, by_doc.cusips)],
        "doc_status": "final",
        "filing_date": by_doc.filing_date.values,
    })
    meta["text"] = meta.accession_number.map(texts)
    meta = meta.dropna(subset=["text"])
    boiler = find_boilerplate(meta.text.tolist(), min_share=0.02, min_docs=20)
    chunks = make_chunks(meta, boiler, pack_boilerplate=True)
    keep = chunks.is_boilerplate | (chunks.seq < chunks_per_doc)
    chunks = chunks[keep].reset_index(drop=True)
    chunks["chunk_id"] = range(len(chunks))
    print(f"청크 {len(chunks):,}개 (상품별 {(~chunks.is_boilerplate).sum():,} + 공통 {chunks.is_boilerplate.sum():,})")
    build_index(con, chunks, COURSE_MODEL)
    con.execute("CHECKPOINT")
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="03_분석_출처_검증_수업자료의 data/ 폴더")
    ap.add_argument("--text", required=True, type=Path, help="02_정규화텍스트의 raw/text/ 폴더")
    ap.add_argument("--db", type=Path, default=COURSE_DB)
    args = ap.parse_args()
    build(args.data, args.text, args.db)


if __name__ == "__main__":
    main()
