"""모듈 3: 구조화 상품 DB (DuckDB).

테이블
  documents        공시 문서 1건 = 1행 (확정본·예비본·FWP)
  document_cusips  문서 ↔ CUSIP (공시 1건에 노트 여러 개가 실리는 1:N 관계)
  terms            424B2 문서에서 추출한 조건 (문서 1건 = 1행)
  underlyings      문서별 기초자산 (문서 1건 = N행)
  quality_issues   품질 점검 결과
뷰
  products         CUSIP 1개 = 상품 1개. 확정 조건 + 예비 조건 + 공시 이력
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from .config import DATA_DIR
from .extract import extract
from .schema import TermSheet

DB_PATH = DATA_DIR / "aifinance.duckdb"
CUSIP_RE = re.compile(r"CUSIP(?:/ISIN| no\.| No\.| number)?\s*:?\s*\|?\s*([0-9A-Z]{9})\b")

TERM_COLUMNS = [f for f in TermSheet.model_fields if f != "underlyings"]

SCHEMA_SQL = """
CREATE OR REPLACE TABLE documents (
    accession_number VARCHAR PRIMARY KEY,
    form             VARCHAR,        -- 424B2 / FWP
    doc_status       VARCHAR,        -- final / preliminary / fwp
    filing_date      DATE,
    url              VARCHAR
);
CREATE OR REPLACE TABLE document_cusips (
    accession_number VARCHAR,
    cusip            VARCHAR,
    PRIMARY KEY (accession_number, cusip)
);
CREATE OR REPLACE TABLE terms (
    accession_number         VARCHAR PRIMARY KEY,
    doc_status               VARCHAR,
    product_name             VARCHAR,
    product_family           VARCHAR,
    principal_amount_usd     DOUBLE,
    cusip                    VARCHAR,
    pricing_date             DATE,
    issue_date               DATE,
    maturity_date            DATE,
    basket_type              VARCHAR,
    coupon_rate_pa           DOUBLE,
    coupon_frequency         VARCHAR,
    coupon_barrier_pct       DOUBLE,
    memory_coupon            BOOLEAN,
    autocall                 BOOLEAN,
    autocall_frequency       VARCHAR,
    autocall_trigger_pct     DOUBLE,
    issuer_callable          BOOLEAN,
    downside_type            VARCHAR,
    barrier_pct              DOUBLE,
    buffer_pct               DOUBLE,
    upside_participation     DOUBLE,
    cap_pct                  DOUBLE,
    digital_return_pct       DOUBLE,
    estimated_value_per_1000 DOUBLE
);
CREATE OR REPLACE TABLE underlyings (
    accession_number VARCHAR,
    seq              INTEGER,
    name             VARCHAR,
    ticker           VARCHAR,
    kind             VARCHAR,
    weight           DOUBLE
);
"""

PRODUCTS_VIEW_SQL = """
CREATE OR REPLACE VIEW products AS
WITH finals AS (
    -- 같은 CUSIP의 확정본이 여러 건이면 가장 늦게 제출된 것을 쓴다 (품질 점검 Q09에서 따로 보고)
    SELECT t.*, d.filing_date AS final_filing_date,
           row_number() OVER (PARTITION BY t.cusip ORDER BY d.filing_date DESC) AS rn
    FROM terms t JOIN documents d USING (accession_number)
    WHERE t.doc_status = 'final' AND t.cusip IS NOT NULL
),
prelim_docs AS (
    SELECT t.*, d.filing_date,
           row_number() OVER (PARTITION BY t.cusip ORDER BY d.filing_date, t.accession_number) AS first_rn,
           row_number() OVER (PARTITION BY t.cusip ORDER BY d.filing_date DESC, t.accession_number DESC) AS last_rn,
           count(*) OVER (PARTITION BY t.cusip) AS prelim_count
    FROM terms t JOIN documents d USING (accession_number)
    WHERE t.doc_status = 'preliminary' AND t.cusip IS NOT NULL
),
prelims AS (
    -- 예비본이 여러 건이면(판매 중 수정 제출) 첫 예비본 = 판매 시작, 마지막 예비본 = 확정 직전 조건
    SELECT l.cusip, l.prelim_count,
           f.filing_date AS prelim_filing_date,
           l.accession_number AS prelim_accession,
           l.coupon_rate_pa AS prelim_coupon_rate_pa,
           f.coupon_rate_pa AS first_prelim_coupon_rate_pa,
           l.upside_participation AS prelim_upside_participation,
           l.cap_pct AS prelim_cap_pct,
           l.estimated_value_per_1000 AS prelim_estimated_value_per_1000,
           1 AS rn
    FROM prelim_docs l JOIN prelim_docs f ON f.cusip = l.cusip AND f.first_rn = 1
    WHERE l.last_rn = 1
),
fwps AS (
    SELECT dc.cusip, count(*) AS fwp_count, min(d.filing_date) AS first_fwp_date
    FROM document_cusips dc JOIN documents d USING (accession_number)
    WHERE d.doc_status = 'fwp'
    GROUP BY dc.cusip
),
und AS (
    SELECT accession_number, count(*) AS n_underlyings,
           string_agg(coalesce(ticker, name), ' / ' ORDER BY seq) AS underlying_names,
           string_agg(DISTINCT kind, ',') AS underlying_kinds
    FROM underlyings GROUP BY accession_number
)
SELECT
    f.cusip,
    f.accession_number AS final_accession,
    f.* EXCLUDE (cusip, accession_number, doc_status, rn),
    round(datediff('day', f.issue_date, f.maturity_date) / 365.25, 2) AS tenor_years,
    u.n_underlyings, u.underlying_names, u.underlying_kinds,
    p.* EXCLUDE (cusip, rn),
    -- 판매 기간: 첫 예비본 제출 → 확정본 제출 (추출값이 아닌 공시일만 쓰므로 견고함)
    datediff('day', p.prelim_filing_date, f.final_filing_date) AS marketing_days,
    coalesce(w.fwp_count, 0) AS fwp_count,
    w.first_fwp_date
FROM finals f
LEFT JOIN prelims p ON p.cusip = f.cusip AND p.rn = 1
LEFT JOIN fwps w ON w.cusip = f.cusip
LEFT JOIN und u ON u.accession_number = f.accession_number
WHERE f.rn = 1
"""


# ------------------------------------------------------------------ 공시 이력
def find_lineage(client, cusips: list[str], forms: str = "424B2,FWP") -> pd.DataFrame:
    """CUSIP별로 EDGAR 전문 검색 → 같은 상품의 FWP·예비본·확정본 목록."""
    frames = []
    for c in cusips:
        _, hits = client.full_text_search(f'"{c}"', forms=forms)
        if len(hits):
            frames.append(hits.assign(cusip=c))
    out = pd.concat(frames, ignore_index=True)
    out["filingDate"] = pd.to_datetime(out.filingDate)
    return out


# ------------------------------------------------------------------ 문서 → 행
def doc_status(form: str, text: str | None) -> str:
    if form == "FWP":
        return "fwp"
    return "preliminary" if text and "PRELIMINARY PRICING SUPPLEMENT" in text[:400].upper() else "final"


def all_cusips(text: str, issuer_prefixes: set[str]) -> list[str]:
    """문서에 나오는 발행사 CUSIP 전부. 'CUSIP:' 표기 + 발행사 접두어(앞 6자리)가 같은 9자리 코드."""
    found = set(CUSIP_RE.findall(text))
    if issuer_prefixes:
        pat = r"\b(?:" + "|".join(sorted(issuer_prefixes)) + r")[0-9A-Z]{3}\b"
        found |= set(re.findall(pat, text))
    return sorted(found)


def build_rows(docs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """docs: accessionNumber, form, filingDate, url, text(FWP 는 없어도 됨), [cusip](FWP 용)"""
    docs = docs.copy()
    docs["doc_status"] = [doc_status(f, t) for f, t in zip(docs.form, docs.get("text", [None] * len(docs)))]
    has_text = docs.text.notna() if "text" in docs else pd.Series(False, index=docs.index)

    terms, unds, links = [], [], []
    for r in docs[has_text & (docs.form == "424B2")].itertuples():  # FWP 는 조건 추출 없이 CUSIP 연결만
        ts = extract(r.text, r.accessionNumber)
        row = ts.model_dump(exclude={"underlyings"})
        row["doc_status"] = r.doc_status
        terms.append(row)
        unds += [{"accession_number": r.accessionNumber, "seq": i, **u.model_dump()} for i, u in enumerate(ts.underlyings)]

    prefixes = {t["cusip"][:6] for t in terms if t["cusip"]}
    for r in docs.itertuples():
        codes = all_cusips(r.text, prefixes) if isinstance(getattr(r, "text", None), str) else []
        if not codes and isinstance(getattr(r, "cusip", None), str):
            codes = [r.cusip]
        links += [{"accession_number": r.accessionNumber, "cusip": c} for c in codes]

    documents = docs.rename(columns={"accessionNumber": "accession_number", "filingDate": "filing_date"})[
        ["accession_number", "form", "doc_status", "filing_date", "url"]
    ]
    return {
        "documents": documents.drop_duplicates("accession_number"),
        "document_cusips": pd.DataFrame(links, columns=["accession_number", "cusip"]).drop_duplicates(),
        "terms": pd.DataFrame(terms)[["accession_number", "doc_status"] + [c for c in TERM_COLUMNS if c != "accession_number"]],
        "underlyings": pd.DataFrame(unds, columns=["accession_number", "seq", "name", "ticker", "kind", "weight"]),
    }


def create_database(rows: dict[str, pd.DataFrame], db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_SQL)
    for table, df in rows.items():
        con.register("_df", df)
        cols = ", ".join(df.columns)
        con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _df")
        con.unregister("_df")
    con.execute(PRODUCTS_VIEW_SQL)
    return con


# ------------------------------------------------------------------ 품질 점검
QUALITY_RULES = [
    ("Q01", "error", "확정본에 CUSIP 없음",
     "SELECT accession_number, NULL AS cusip, product_name AS detail FROM terms WHERE doc_status='final' AND cusip IS NULL"),
    ("Q02", "error", "확정본에 가격결정일·만기일 없음",
     "SELECT accession_number, cusip, concat('pricing=', pricing_date, ' maturity=', maturity_date) FROM terms "
     "WHERE doc_status='final' AND (pricing_date IS NULL OR maturity_date IS NULL)"),
    ("Q03", "error", "날짜 순서 오류 (가격결정일 ≤ 발행일 < 만기일)",
     "SELECT accession_number, cusip, concat(pricing_date, ' / ', issue_date, ' / ', maturity_date) FROM terms "
     "WHERE pricing_date > issue_date OR issue_date >= maturity_date"),
    ("Q04", "warning", "비율 값이 상식 범위 밖",
     "SELECT accession_number, cusip, concat('barrier=', barrier_pct, ' buffer=', buffer_pct, ' coupon=', coupon_rate_pa) FROM terms "
     "WHERE barrier_pct NOT BETWEEN 0.05 AND 1.0 OR buffer_pct NOT BETWEEN 0.01 AND 0.6 OR coupon_rate_pa NOT BETWEEN 0.005 AND 0.6"),
    ("Q05", "warning", "추정가치가 $850~$1,000 범위 밖",
     "SELECT accession_number, cusip, estimated_value_per_1000::VARCHAR FROM terms "
     "WHERE doc_status='final' AND estimated_value_per_1000 NOT BETWEEN 850 AND 1000"),
    ("Q06", "warning", "상품군과 핵심 조건 불일치",
     "SELECT accession_number, cusip, product_family FROM terms WHERE doc_status='final' AND ("
     " (product_family LIKE '%contingent_coupon' AND coupon_rate_pa IS NULL)"
     " OR (product_family='leveraged_buffer' AND buffer_pct IS NULL)"
     " OR (product_family='leveraged_barrier' AND barrier_pct IS NULL)"
     " OR (product_family LIKE 'autocall%' AND NOT autocall))"),
    ("Q07", "warning", "상품군 미분류 (other)",
     "SELECT accession_number, cusip, product_name FROM terms WHERE doc_status='final' AND product_family='other'"),
    ("Q08", "info", "공시 1건에 CUSIP 여러 개 (노트 여러 종)",
     "SELECT accession_number, NULL, string_agg(cusip, ', ') FROM document_cusips dc JOIN documents d USING (accession_number) "
     "WHERE d.doc_status <> 'fwp' GROUP BY accession_number HAVING count(*) > 1"),
    ("Q09", "warning", "같은 CUSIP의 확정본이 여러 건",
     "SELECT string_agg(accession_number, ', '), cusip, count(*)::VARCHAR FROM terms WHERE doc_status='final' AND cusip IS NOT NULL "
     "GROUP BY cusip HAVING count(*) > 1"),
    ("Q10", "warning", "확정 쿠폰이 예비본 하한보다 낮음",
     "SELECT final_accession, cusip, concat(prelim_coupon_rate_pa, ' → ', coupon_rate_pa) FROM products "
     "WHERE coupon_rate_pa < prelim_coupon_rate_pa - 1e-9"),
    ("Q11", "info", "확정본에 대응하는 예비본을 찾지 못함",
     "SELECT final_accession, cusip, product_family FROM products WHERE prelim_accession IS NULL"),
    ("Q12", "info", "판매 중 예비본 수정으로 쿠폰 하한 변경",
     "SELECT final_accession, cusip, concat(first_prelim_coupon_rate_pa, ' → ', prelim_coupon_rate_pa, ' → 확정 ', coupon_rate_pa) "
     "FROM products WHERE first_prelim_coupon_rate_pa <> prelim_coupon_rate_pa"),
]


def run_quality_checks(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """규칙을 모두 실행해 quality_issues 테이블을 만들고 규칙별 건수를 돌려준다."""
    con.execute("CREATE OR REPLACE TABLE quality_issues (rule_id VARCHAR, severity VARCHAR, rule VARCHAR, "
                "accession_number VARCHAR, cusip VARCHAR, detail VARCHAR)")
    for rule_id, severity, desc, sql in QUALITY_RULES:
        con.execute(f"INSERT INTO quality_issues SELECT '{rule_id}', '{severity}', '{desc}', * FROM ({sql})")
    return con.execute("""
        SELECT r.rule_id, r.severity, r.rule, count(q.rule_id) AS n_issues
        FROM (SELECT DISTINCT rule_id, severity, rule FROM quality_issues
              UNION SELECT * FROM (VALUES """ + ", ".join(f"('{a}','{b}','{c}')" for a, b, c, _ in QUALITY_RULES) + """)) r
        LEFT JOIN quality_issues q USING (rule_id)
        GROUP BY ALL ORDER BY r.rule_id""").df()
