"""모듈 4: Claude Desktop 용 MCP 서버.

상품 DB(SQL)와 공시 원문 검색(RAG)을 Claude 에게 도구로 제공한다.

    uv run python -m aifinance.mcp_server            # stdio 로 실행 (Claude Desktop 이 띄움)

DB 두 개를 쓴다.
- SQL 질의용 (AIFINANCE_DB): 전체 기간 DB 가 있으면 그것, 없으면 표본 DB
- 원문 검색용 (AIFINANCE_INDEX_DB): 색인을 만든 표본 DB. 조건의 정의·위험·산정 방식 같은 설명은
  상품군마다 공통이라 표본 색인으로 충분하고, 전체 색인은 노트북 CPU 로 1시간 이상 걸린다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer

from .config import DATA_DIR

_FULL, _SAMPLE = DATA_DIR / "aifinance_full.duckdb", DATA_DIR / "aifinance.duckdb"
DB_PATH = Path(os.getenv("AIFINANCE_DB", _FULL if _FULL.exists() else _SAMPLE))
INDEX_PATH = Path(os.getenv("AIFINANCE_INDEX_DB", _SAMPLE))
MAX_ROWS = 200

INSTRUCTIONS = """\
JP Morgan 구조화 노트(발행: JPMorgan Chase Financial Company LLC) 데이터베이스입니다. SEC EDGAR 424B2·FWP 공시에서 추출했습니다.

도구 선택 원칙:
- 숫자·속성·집계 질문(쿠폰 평균, 상품군별 건수, 배리어 분포 등) → query_products (SQL). 먼저 describe_database 로 구조를 확인하세요.
- 조건의 의미·정의·위험·계산 방식 등 설명 질문 → search_filings. 공시가 영어이므로 검색어는 영어로,
  그리고 사용자의 말을 그대로 옮기지 말고 424B2 공시가 쓰는 용어로 바꿔 쓰세요
  (예: "은행이 매긴 적정가" → "estimated value of the notes internal pricing models").
  첫 검색 결과가 질문과 안 맞으면 다른 용어로 한두 번 더 검색하세요.
- 특정 상품 하나 → get_product(cusip).

답변 원칙:
- 비율 컬럼은 소수입니다 (0.70 = 70%). 사용자에게는 %로 바꿔 보여 주세요.
- 근거가 된 상품의 CUSIP 과 EDGAR 공시 링크를 밝히세요.
- 데이터는 추출기로 만든 것이라 오류가 있을 수 있습니다. 이상한 값은 search_filings 나 get_product 로 원문을 확인하세요.
"""

server = MCPServer(name="aifinance", instructions=INSTRUCTIONS)


def _connect(path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    if not path.exists():
        raise FileNotFoundError(f"DB 파일이 없습니다: {path}. 노트북 03·04를 먼저 실행하세요.")
    return duckdb.connect(str(path), read_only=True)


def _table(df) -> str:
    if df.empty:
        return "(결과 없음)"
    return df.to_markdown(index=False, floatfmt=".4g")


@server.tool()
def describe_database() -> str:
    """상품 DB 의 테이블·컬럼 구조, 상품군 목록, 단위 규칙을 보여 준다. SQL 을 쓰기 전에 먼저 호출하라."""
    con = _connect()
    try:
        parts = [f"SQL DB: {DB_PATH.name} / 검색 색인: {INDEX_PATH.name}"]
        for name in ["products", "underlyings", "documents", "quality_issues"]:
            cols = con.execute(f"DESCRIBE {name}").df()[["column_name", "column_type"]]
            n = con.execute(f"SELECT count(*) FROM {name}").fetchall()[0][0]
            parts.append(f"### {name} ({n:,}행)\n" + _table(cols))
        fam = con.execute("SELECT product_family, count(*) AS n FROM products GROUP BY 1 ORDER BY 2 DESC").df()
        parts.append("### product_family 값\n" + _table(fam))
        parts.append(
            "### 규칙\n"
            "- products: CUSIP 1개 = 상품 1행. 확정본 조건 + prelim_* (마지막 예비본 조건) + 공시 이력.\n"
            "- 비율 컬럼(*_pct, coupon_rate_pa, upside_participation)은 소수. estimated_value_per_1000 은 액면 $1,000 당 달러.\n"
            "- 기초자산별 집계는 underlyings 를 products.final_accession = underlyings.accession_number 로 조인.\n"
            "- quality_issues: 추출 품질 점검 결과 (severity = error/warning/info)."
        )
        return "\n\n".join(parts)
    finally:
        con.close()


FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|COPY|EXPORT|IMPORT|INSTALL|LOAD|PRAGMA|SET|CALL)\b", re.I)


@server.tool()
def query_products(sql: str) -> str:
    """상품 DB 에 읽기 전용 SQL(DuckDB 문법)을 실행한다. SELECT/WITH 한 문장만 허용, 최대 200행.

    예: SELECT product_family, count(*), avg(coupon_rate_pa) FROM products GROUP BY 1
    """
    stmt = sql.strip().rstrip(";")
    if ";" in stmt or not re.match(r"^\s*(SELECT|WITH)\b", stmt, re.I) or FORBIDDEN.search(stmt):
        return "오류: SELECT 또는 WITH 로 시작하는 읽기 전용 쿼리 한 문장만 실행할 수 있습니다."
    con = _connect()
    try:
        df = con.execute(f"SELECT * FROM ({stmt}) LIMIT {MAX_ROWS + 1}").df()
    except duckdb.Error as e:
        return f"SQL 오류: {e}"
    finally:
        con.close()
    note = f"\n\n(처음 {MAX_ROWS}행만 표시. 집계나 LIMIT 를 쓰세요.)" if len(df) > MAX_ROWS else ""
    return _table(df.head(MAX_ROWS)) + note


@server.tool()
def search_filings(query: str, k: int = 6, product_family: str | None = None, cusip: str | None = None,
                   include_boilerplate: bool = True) -> str:
    """공시 원문을 하이브리드(의미 + 키워드) 검색한다. 검색어는 영어로 쓴다.

    색인은 표본 공시(확정본 약 150건)와 공통 문구로 만들어져 있다. 조건의 정의·위험·산정 방식 설명에 쓰고,
    특정 상품의 숫자는 query_products / get_product 로 확인한다.

    product_family 나 cusip 으로 범위를 좁힐 수 있다. include_boilerplate=False 면 상품별 고유 문단만 찾는다.
    결과마다 상품명·CUSIP·공시일 머리글과 EDGAR 링크가 붙는다.
    """
    from .rag import search

    where = []
    if product_family:
        where.append(f"p.product_family = '{product_family.replace(chr(39), '')}'")
    if cusip:
        where.append(f"c.cusip = '{cusip.replace(chr(39), '')}'")
    con = _connect(INDEX_PATH)
    try:
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'chunks'").fetchall()[0][0]:
            return "검색 색인이 없습니다. 노트북 04에서 build_index 를 먼저 실행하세요."
        hits = search(con, query, k=min(k, 15), where=" AND ".join(where) or None,
                      include_boilerplate=include_boilerplate)
        urls = dict(con.execute("SELECT accession_number, url FROM documents").fetchall())
    finally:
        con.close()
    if hits.empty:
        return "(검색 결과 없음)"
    out = []
    for i, h in enumerate(hits.itertuples(), 1):
        out.append(f"--- 결과 {i} | {h.product_family or ''} | 출처: {urls.get(h.accession_number, h.accession_number)}\n{h.text}")
    return "\n\n".join(out)


@server.tool()
def get_product(cusip: str) -> str:
    """CUSIP 하나의 확정 조건, 예비본 조건, 기초자산, 공시 이력(EDGAR 링크)을 보여 준다."""
    con = _connect()
    try:
        row = con.execute("SELECT * FROM products WHERE cusip = ?", [cusip]).df()
        if row.empty:
            return f"CUSIP {cusip} 상품이 DB에 없습니다."
        acc = row.final_accession.iloc[0]
        unds = con.execute("SELECT name, ticker, kind, weight FROM underlyings WHERE accession_number = ? ORDER BY seq", [acc]).df()
        docs = con.execute("""
            SELECT d.form, d.doc_status, d.filing_date, d.url FROM document_cusips dc JOIN documents d USING (accession_number)
            WHERE dc.cusip = ? ORDER BY d.filing_date""", [cusip]).df()
        issues = con.execute("SELECT rule_id, rule, detail FROM quality_issues WHERE cusip = ? OR accession_number = ?", [cusip, acc]).df()
    finally:
        con.close()
    terms = {k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in row.iloc[0].to_dict().items() if v == v and v is not None}
    parts = ["### 조건\n```json\n" + json.dumps(terms, ensure_ascii=False, indent=1, default=str) + "\n```",
             "### 기초자산\n" + _table(unds),
             "### 공시 이력\n" + _table(docs)]
    if not issues.empty:
        parts.append("### 품질 점검 경고\n" + _table(issues))
    return "\n\n".join(parts)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
