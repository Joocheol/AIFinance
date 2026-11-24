# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]"]
# ///
"""강사의 공용 상품 DB 채우기: 데이터베이스 jpm, 표 products(읽기 전용 계정 student_ro).

    SHARED_HOST=<서버 주소> SHARED_ADMIN_PW_FILE=<관리자 비밀번호 파일> SHARED_RO_PW_FILE=<읽기 계정 비밀번호 파일> \
      uv run shinhan_v3/tools/load_shared.py [<products_in_period.csv>]

비밀번호는 파일에서 읽고 화면에 쓰지 않는다. 표는 지우고 다시 만든다.
칸: 수업 DB(course_db.PRODUCT_COLUMNS)와 같은 45칸. 날짜 칸은 date, 숫자 칸은 numeric, 나머지는 text.
"""

import csv
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parents[2]
COLS = ["product_key", "cusip", "isin", "accession", "filing_date", "title", "issuer", "guarantor",
        "pricing_date", "trade_date", "issue_date", "maturity_date", "tenor_years", "currency",
        "principal", "public_offering_amount", "issue_price_per_1000", "estimated_value_per_1000", "price_value_gap_pct",
        "product_type", "contract_class", "underliers", "tickers", "underlier_structure",
        "coupon_type", "coupon_annual_pct", "coupon_frequency", "memory", "autocall", "issuer_call",
        "coupon_barrier_pct", "principal_barrier_pct", "buffer_pct", "cap_pct", "participation",
        "principal_protection", "barrier_observation", "coupon_observation",
        "multiple_products_flag", "split_rule", "confidence", "human_review_status", "missing_fields",
        "related_accessions", "primary_document_url"]
DATES = {"filing_date", "pricing_date", "trade_date", "issue_date", "maturity_date"}


def is_num(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "data/sec_v3/pipe/data/products_in_period.csv"
    host = os.environ["SHARED_HOST"]
    admin_pw = Path(os.environ["SHARED_ADMIN_PW_FILE"]).read_text().strip()
    ro_pw = Path(os.environ["SHARED_RO_PW_FILE"]).read_text().strip()
    with src.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    types = {}
    for c in COLS:
        vals = [r[c] for r in rows if r.get(c, "") != ""]
        types[c] = "date" if c in DATES else ("numeric" if vals and all(is_num(v) for v in vals) else "text")

    kw = dict(host=host, user="jpmadmin", password=admin_pw, sslmode="require", autocommit=True, connect_timeout=20)
    with psycopg.connect(dbname="postgres", **kw) as con:
        if not con.execute("select 1 from pg_database where datname='jpm'").fetchone():
            con.execute("create database jpm")
    with psycopg.connect(dbname="jpm", **kw) as con:
        con.execute("drop table if exists products")
        con.execute("create table products (" + ", ".join(f'"{c}" {types[c]}' for c in COLS) + ")")
        with con.cursor().copy("copy products (" + ", ".join(f'"{c}"' for c in COLS) + ") from stdin") as cp:
            for r in rows:
                cp.write_row([r.get(c) or None for c in COLS])
        con.execute("create index on products (accession)")
        con.execute("create index on products (cusip)")
        con.execute("analyze products")
        if not con.execute("select 1 from pg_roles where rolname='student_ro'").fetchone():
            con.execute(sql.SQL("create role student_ro login password {}").format(sql.Literal(ro_pw)))
        else:
            con.execute(sql.SQL("alter role student_ro password {}").format(sql.Literal(ro_pw)))
        for q in ("grant connect on database jpm to student_ro", "grant usage on schema public to student_ro",
                  "grant select on products to student_ro", "revoke create on schema public from public"):
            con.execute(q)
        n, k, s = con.execute("select count(*), count(principal), round(sum(principal)/1e9, 2) from products").fetchone()
    print(f"products {n:,}행 (원금 확인 {k:,}, 합계 ${s}B), 숫자 칸 {sum(t == 'numeric' for t in types.values())}개 → jpm.products, 읽기 계정 student_ro")


if __name__ == "__main__":
    main()
