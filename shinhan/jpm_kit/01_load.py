# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]>=3.2", "pydantic>=2", "pandas>=2"]
# ///
"""활동 3 — 2026년 9월 공시 1,890건과 상품 표를 내 Azure PostgreSQL에 넣는다.

만드는 표
  filings         공시 1건 = 1행 (accession, month, chars, body)
  chunks          공시를 검색 단위(최대 1,200자)로 자른 조각. tsv = 키워드 색인(자동), emb = 벡터(04_embed.py가 채움)
  products        강사가 같은 파이프라인으로 만든 12개월 상품 표 10,410행 (상품 1개 = 1행)
  data_dictionary products 컬럼의 뜻과 단위

실행: uv run jpm_kit/01_load.py
다시 실행하면 이미 적재된 표는 건너뜁니다. 처음부터 다시: --force
실험용 청크 표 만들기(활동 6): --table chunks_a --header  /  --table chunks_b --max-chars 600
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time

import kit_common as kc

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="이미 있는 표를 지우고 다시 만든다")
ap.add_argument("--table", default="chunks", help="청크를 넣을 표 이름 (실험용: chunks_a 등)")
ap.add_argument("--max-chars", type=int, default=kc.MAX_CHARS, help="청크 최대 글자 수 (기본 1200)")
ap.add_argument("--header", action="store_true", help="청크 앞에 상품명·CUSIP·문서 종류 머리글을 붙인다 (실험 A)")
args = ap.parse_args()
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", args.table):
    raise SystemExit("표 이름은 영문 소문자·숫자·밑줄만 쓸 수 있습니다.")

t_all = time.time()
conn = kc.connect()
cur = conn.cursor()
print("DB 연결 성공", flush=True)
cur.execute("CREATE EXTENSION IF NOT EXISTS vector")


def exists(table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    return cur.fetchone()[0]


def count(table: str) -> int:
    cur.execute(f"SELECT count(*) FROM {table}")
    return cur.fetchone()[0]


texts = None
only_chunks = args.table != "chunks"

# ---------------------------------------------------------------- 1) filings
if not only_chunks:
    if exists("filings") and not args.force:
        print(f"[건너뜀] filings 표가 이미 있습니다 ({count('filings'):,}행)")
    else:
        t0 = time.time()
        texts = kc.read_month_texts()
        cur.execute("DROP TABLE IF EXISTS filings")
        cur.execute("CREATE TABLE filings (accession text PRIMARY KEY, month text, chars int, body text)")
        with cur.copy("COPY filings (accession, month, chars, body) FROM STDIN") as cp:
            for acc, body in texts.items():
                cp.write_row((acc, kc.MONTH, len(body), body))
        print(f"filings: {len(texts):,}건, {sum(map(len, texts.values())) / 1e6:.1f}백만 자 적재 ({time.time() - t0:.0f}초)", flush=True)

# ---------------------------------------------------------------- 2) chunks
tbl = args.table
if exists(tbl) and not args.force:
    print(f"[건너뜀] {tbl} 표가 이미 있습니다 ({count(tbl):,}행). 다시 만들려면 --force")
else:
    t0 = time.time()
    texts = texts or kc.read_month_texts()
    headers = None
    if args.header:
        import kit_extract as kx

        prod = {}
        with open(kc.DATA / "products.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                prod.setdefault(r["accession"], []).append(r["cusip"])
        headers = {}
        for acc, body in texts.items():
            title = kx.extract_title(body) or "상품명 미상"
            kind = "예비" if re.search(r"PRELIMINARY|Subject to Completion", body[:4000], re.I) else "최종/기타"
            cusips = ", ".join(sorted(set(prod.get(acc, [])))[:3]) or "-"
            headers[acc] = f"[{title[:160]} | CUSIP {cusips} | {kind}]"
    rows = kc.make_chunks(texts, max_chars=args.max_chars, headers=headers)
    cur.execute(f"DROP TABLE IF EXISTS {tbl}")
    cur.execute(f"""CREATE TABLE {tbl} (
        chunk_id int PRIMARY KEY, accession text, seq int, is_boilerplate bool, body text,
        tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED,
        emb vector({kc.EMB_DIM}))""")
    with cur.copy(f"COPY {tbl} (chunk_id, accession, seq, is_boilerplate, body) FROM STDIN") as cp:
        for i, (acc, seq, bp, body) in enumerate(rows):
            cp.write_row((i, acc, seq, bp, body))
    print(f"{tbl}: {len(rows):,}개 청크 (공통 문구 {sum(r[2] for r in rows):,}개, 최대 {args.max_chars}자"
          f"{', 머리글 붙임' if args.header else ''}) ({time.time() - t0:.0f}초)", flush=True)
    t0 = time.time()
    cur.execute(f"CREATE INDEX {tbl}_tsv_gin ON {tbl} USING gin(tsv)")
    print(f"키워드 색인(GIN) 생성 ({time.time() - t0:.0f}초)", flush=True)

# ---------------------------------------------------------------- 3) products, data_dictionary
if not only_chunks:
    if exists("products") and not args.force:
        print(f"[건너뜀] products 표가 이미 있습니다 ({count('products'):,}행)")
    else:
        t0 = time.time()
        schema = json.loads((kc.DATA / "products_schema.json").read_text(encoding="utf-8"))
        cols = list(schema)
        cur.execute("DROP TABLE IF EXISTS products")
        cur.execute("CREATE TABLE products (" + ", ".join(f'"{c}" {schema[c]}' for c in cols) + ")")
        with open(kc.DATA / "products.csv", encoding="utf-8") as f, \
                cur.copy("COPY products (" + ", ".join(f'"{c}"' for c in cols) + ") FROM STDIN") as cp:
            for r in csv.DictReader(f):
                cp.write_row([r[c] if r[c] != "" else None for c in cols])
        cur.execute("CREATE INDEX products_cusip ON products (cusip)")
        print(f"products: {count('products'):,}개 상품 ({time.time() - t0:.0f}초)", flush=True)

    if exists("data_dictionary") and not args.force:
        print("[건너뜀] data_dictionary 표가 이미 있습니다")
    else:
        cur.execute("DROP TABLE IF EXISTS data_dictionary")
        cur.execute("CREATE TABLE data_dictionary (field text, description_ko text, type text, csv_unit text, missing text)")
        with open(kc.KIT / "project_knowledge" / "data_dictionary.csv", encoding="utf-8-sig") as f, \
                cur.copy("COPY data_dictionary FROM STDIN") as cp:
            for r in csv.DictReader(f):
                cp.write_row([r.get(c) or None for c in ("field", "description_ko", "type", "csv_unit", "missing")])
        print(f"data_dictionary: {count('data_dictionary')}개 컬럼 설명", flush=True)

# ---------------------------------------------------------------- 요약
print("\n내 DB의 표:")
print(kc.sql_table(cur, """SELECT relname AS 표,
       (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I', relname), false, true, '')))[1]::text::bigint AS 행수,
       pg_size_pretty(pg_total_relation_size(relid)) AS 크기
     FROM pg_stat_user_tables ORDER BY relname"""))
cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print(f"\nDB 전체 크기: {cur.fetchone()[0]} / 걸린 시간 {time.time() - t_all:.0f}초")
print("다음: 04_embed.py 로 벡터화를 백그라운드에서 시작하고, 02_extract.py 로 상품 조건을 추출합니다.")
