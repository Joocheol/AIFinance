# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]>=3.2", "pydantic>=2", "pandas>=2"]
# ///
"""활동 4 — 9월 공시에서 상품 조건을 규칙으로 추출해 my_products 표에 넣고, 정답 27건과 필드별로 채점한다.

추출 규칙은 kit_extract.py 의 extract() 에 있습니다. 규칙을 고친 뒤 이 스크립트를 다시 실행하면 재채점됩니다.
채점 결과는 out/extract_score.csv, 틀린 사례는 out/extract_errors.csv 에 저장됩니다.

실행: uv run jpm_kit/02_extract.py            (채점 + my_products 적재)
      uv run jpm_kit/02_extract.py --score-only  (DB에 쓰지 않고 채점만, 규칙 고칠 때 빠르게)
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

import kit_common as kc
import kit_extract as kx

ap = argparse.ArgumentParser()
ap.add_argument("--score-only", action="store_true", help="정답 27건 채점만 하고 DB에는 쓰지 않는다")
args = ap.parse_args()
kc.OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- 1) 정답 27건 채점
gold = kx.load_gold(kc.DATA / "gold")
gold_texts = {p.stem: p.read_text(encoding="utf-8", errors="replace") for p in (kc.DATA / "gold_texts").glob("*.txt")}
preds = {a: kx.extract(gold_texts[a], a) for a in gold if a in gold_texts}
cmp = kx.compare(preds, gold)
acc = kx.field_accuracy(cmp)
overall = acc.correct.sum() / acc[["correct", "wrong", "missed", "spurious"]].sum().sum()
acc.to_csv(kc.OUT / "extract_score.csv", encoding="utf-8-sig")
cmp[cmp.outcome != "correct"].to_csv(kc.OUT / "extract_errors.csv", index=False, encoding="utf-8-sig")

print(f"정답 {len(gold)}건 × {len(kx.EVAL_FIELDS)}개 필드 채점 (correct=맞음, wrong=틀림, missed=놓침, spurious=헛추출)\n")
show = acc.sort_values("accuracy")
print(show.to_string())
print(f"\n전체 정확도: {overall:.1%}")
print(f"정확도가 가장 낮은 필드 3개: {', '.join(show.index[:3])}")
print("틀린 사례 목록: jpm_kit/out/extract_errors.csv (field, gold=정답, pred=추출값)")

if args.score_only:
    raise SystemExit

# ---------------------------------------------------------------- 2) 9월 1,890건 추출 → my_products
t0 = time.time()
texts = kc.read_month_texts()
rows, failed = [], 0
for a, text in texts.items():
    try:
        d = kx.extract(text, a).model_dump()
    except Exception:  # noqa: BLE001  형식이 다른 문서는 건너뜀
        failed += 1
        continue
    rows.append({
        "accession": a, "product_name": d["product_name"] or None, "cusip": d["cusip"], "family": d["product_family"],
        "principal": d["principal_amount_usd"], "pricing_date": d["pricing_date"], "maturity_date": d["maturity_date"],
        "underlyings": ", ".join(u["name"] for u in d["underlyings"]) or None, "basket_type": d["basket_type"],
        "coupon_rate_pa": d["coupon_rate_pa"], "coupon_barrier_pct": d["coupon_barrier_pct"],
        "barrier_pct": d["barrier_pct"], "buffer_pct": d["buffer_pct"], "autocall": d["autocall"],
        "estimated_value_per_1000": d["estimated_value_per_1000"]})
mp = pd.DataFrame(rows)
print(f"\n9월 공시 {len(texts):,}건 추출: 성공 {len(mp):,}건, 실패 {failed}건 ({time.time() - t0:.0f}초)")

conn = kc.connect()
cur = conn.cursor()
cur.execute("DROP TABLE IF EXISTS my_products")
cur.execute("""CREATE TABLE my_products (accession text, product_name text, cusip text, family text, principal double precision,
  pricing_date date, maturity_date date, underlyings text, basket_type text, coupon_rate_pa double precision,
  coupon_barrier_pct double precision, barrier_pct double precision, buffer_pct double precision, autocall bool,
  estimated_value_per_1000 double precision)""")
with cur.copy("COPY my_products FROM STDIN") as cp:
    for r in mp.itertuples(index=False):
        cp.write_row([None if (v is None or (isinstance(v, float) and pd.isna(v))) else v for v in r])
print(kc.sql_table(cur, """SELECT count(*) AS 행수, count(DISTINCT cusip) AS 서로다른_CUSIP, count(principal) AS 원금있음,
                                  count(coupon_rate_pa) AS 쿠폰있음, count(estimated_value_per_1000) AS 추정가치있음 FROM my_products"""))
print("\n생각해 보기: my_products 행 수와 서로 다른 CUSIP 수는 왜 다를까요? products 표의 9월 제출 상품 수와도 비교해 보세요.")
