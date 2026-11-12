"""기간 전체 수집 → 추출 → DB 파이프라인.

    uv run python -m aifinance.pipeline --start 2026-08-12 --end 2026-11-10

지정 기간의 JPM 발행사 424B2·FWP 를 모두 내려받아 data/aifinance_full.duckdb 를 만든다.
- 90일이면 약 6,000건, 1GB 내외. SEC 속도 제한 때문에 30~40분 걸린다. 받은 문서는 캐시되므로 다시 돌리면 빠르다.
- 예비본은 확정본보다 1~3주 먼저 제출되므로, 분석할 기간보다 2주 앞서 --start 를 잡아야 예비본–확정본이 짝지어진다.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor

import pandas as pd
from tqdm import tqdm

from .config import DATA_DIR, JPM_FINANCIAL_CIK
from .db import build_rows, create_database, run_quality_checks
from .edgar import EdgarClient, html_to_text

TEXT_DIR = DATA_DIR / "text"


def _to_text(path: str) -> str:
    from pathlib import Path

    return html_to_text(Path(path).read_bytes())


def collect(start: str, end: str, forms=("424B2", "FWP"), client: EdgarClient | None = None) -> pd.DataFrame:
    client = client or EdgarClient()
    filings = client.list_filings(JPM_FINANCIAL_CIK)
    if filings.filingDate.min() > pd.Timestamp(start):
        filings = client.list_filings(JPM_FINANCIAL_CIK, include_older=True)
    sel = filings[filings.form.isin(forms) & filings.filingDate.between(start, end)].reset_index(drop=True)

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    text_paths = [TEXT_DIR / f"{a}.txt" for a in sel.accessionNumber]
    todo = [(i, url) for i, (url, p) in enumerate(zip(sel.url, text_paths)) if not p.exists()]
    raw = {i: str(client.download(url)) for i, url in tqdm(todo, desc="다운로드")}
    with ProcessPoolExecutor() as pool:  # HTML → 평문 변환은 CPU 작업이라 병렬로
        for i, text in zip(raw, tqdm(pool.map(_to_text, raw.values(), chunksize=16), total=len(raw), desc="평문 변환")):
            text_paths[i].write_text(text)
    sel["text"] = [p.read_text() for p in text_paths]
    return sel[["accessionNumber", "form", "filingDate", "url", "text"]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--db", default=str(DATA_DIR / "aifinance_full.duckdb"))
    args = ap.parse_args()

    docs = collect(args.start, args.end)
    print(f"문서 {len(docs):,}건 → 추출 중…")
    con = create_database(build_rows(docs), db_path=__import__("pathlib").Path(args.db))
    print(run_quality_checks(con).to_string(index=False))
    print(con.sql("SELECT count(*) AS products, count(prelim_accession) AS with_prelim FROM products").df().to_string(index=False))


if __name__ == "__main__":
    main()
