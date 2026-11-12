"""신한은행 수업용 원격 MCP 서버 (Claude 커스텀 커넥터용).

    uv run python -m aifinance.course_server            # http://0.0.0.0:8000/mcp

- DB: data/shinhan_jpm.duckdb (course_db.py 로 생성, Dropbox 수업 자료 12개월 기준). COURSE_DB 로 변경 가능
- 읽기 전용, 결과는 짧게(Claude Pro 사용량 절약), 분당 요청 수 제한(RATE_LIMIT_PER_MIN)
- GET /healthz : 상태 확인 (Azure Container Apps 프로브)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .config import DATA_DIR

DB_PATH = Path(os.getenv("COURSE_DB", DATA_DIR / "shinhan_jpm.duckdb"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "50"))
MAX_CELL = 160  # 표의 긴 문자열은 잘라서 보여 준다
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))

INSTRUCTIONS = """\
JP Morgan 구조화 노트 수업 데이터입니다 (SEC EDGAR 424B2, 예정 발행일 2025-10-01~2026-09-30, 상품 10,410개).
신한은행 FE/RM 수업 Excel 과 같은 데이터·같은 분모입니다.

도구 선택:
- 숫자·집계·비교 → query_products (SQL). 처음에는 describe_database 로 컬럼 뜻과 단위를 확인하세요.
- 조건의 의미·위험·계산 방식 → search_filings. 공시가 영어이므로 검색어는 424B2 공시 용어(영어)로 쓰세요.
- 특정 상품 → get_product(cusip).

반드시 지킬 규칙:
- *_pct 컬럼은 퍼센트포인트입니다 (coupon_annual_pct = 10.75 → 연 10.75%).
- 결측(NULL)은 0 이 아닙니다. 합계·평균을 낼 때 몇 개가 비어 있는지 함께 밝히세요.
- 공시 건수(filings)와 상품 수(products)를 구분하세요. 한 공시에 상품이 여러 개일 수 있습니다.
- price_value_gap_pct(발행가격과 최초 추정가치의 차이)는 발행사 순이익이 아닙니다. '가격·가치 차이'라고 부르세요.
- product_type 은 '계약조건 근거 규칙 분류(잠정)'이며 사람 전수 검토 전입니다.
- 근거가 된 CUSIP 과 SEC 원문 링크를 밝히고, 확인하지 못한 것은 '확인하지 못함'이라고 쓰세요.
"""

server = MCPServer(name="jpm-424b2-course", instructions=INSTRUCTIONS)


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


def _clip(v):
    if isinstance(v, str) and len(v) > MAX_CELL:
        return v[:MAX_CELL] + "…"
    return v


def _table(df) -> str:
    if df.empty:
        return "(결과 없음)"
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(_clip)
    return df.to_markdown(index=False, floatfmt=".4g")


@server.tool()
def describe_database() -> str:
    """테이블·컬럼 구조와 각 컬럼의 한국어 설명·단위, 상품 분류 목록을 보여 준다. SQL 을 쓰기 전에 먼저 호출하라."""
    con = _connect()
    try:
        cols = con.execute("""
            SELECT c.table_name AS 테이블, c.column_name AS 컬럼, c.data_type AS 타입,
                   coalesce(d.description_ko, '') AS 설명, coalesce(d.csv_unit, '') AS 단위
            FROM information_schema.columns c LEFT JOIN data_dictionary d ON d.field = c.column_name
            WHERE c.table_name IN ('products', 'filings')
            ORDER BY c.table_name DESC, c.ordinal_position""").df()
        counts = con.execute("""SELECT (SELECT count(*) FROM products) AS 상품수,
                                       (SELECT count(DISTINCT accession) FROM products) AS 상품공시수,
                                       (SELECT count(*) FROM filings) AS 전체공시수""").df()
        types = con.execute("SELECT product_type, count(*) AS n FROM products GROUP BY 1 ORDER BY 2 DESC").df()
    finally:
        con.close()
    cols["설명"] = cols["설명"].str.slice(0, 70)
    return "\n\n".join([
        "### 규모\n" + _table(counts),
        "### 컬럼 (products: 상품 1개 = 1행, filings: 공시 1건 = 1행)\n" + cols.to_markdown(index=False),
        "### product_type (계약조건 근거 규칙 분류, 잠정)\n" + _table(types),
    ])


FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|COPY|EXPORT|IMPORT|INSTALL|LOAD|PRAGMA|SET|CALL|read_\w+)\b", re.I)


@server.tool()
def query_products(sql: str) -> str:
    """읽기 전용 SQL(DuckDB 문법) 한 문장을 실행한다. 테이블: products, filings, data_dictionary. 최대 50행.

    예: SELECT product_type, count(*) AS n, round(avg(coupon_annual_pct), 2) AS 평균쿠폰 FROM products GROUP BY 1 ORDER BY n DESC
    """
    stmt = sql.strip().rstrip(";")
    if ";" in stmt or not re.match(r"^\s*(SELECT|WITH)\b", stmt, re.I) or FORBIDDEN.search(stmt):
        return "오류: SELECT 또는 WITH 로 시작하는 읽기 전용 쿼리 한 문장만 실행할 수 있습니다."
    con = _connect()
    try:
        df = con.execute(f"SELECT * FROM ({stmt}) LIMIT {MAX_ROWS + 1}").df()
    except duckdb.Error as e:
        return f"SQL 오류: {str(e)[:500]}"
    finally:
        con.close()
    if "embedding" in df.columns:
        df = df.drop(columns=["embedding"])
    note = f"\n\n(처음 {MAX_ROWS}행만 표시했습니다. 집계나 LIMIT 를 쓰세요.)" if len(df) > MAX_ROWS else ""
    return _table(df.head(MAX_ROWS)) + note


@server.tool()
def search_filings(query: str, k: int = 5, cusip: str | None = None, product_type: str | None = None) -> str:
    """공시 원문(확정 424B2)을 의미+키워드로 검색한다. 검색어는 공시 용어(영어)로 쓴다.

    cusip 이나 product_type 으로 범위를 좁힐 수 있다. 결과마다 상품명·CUSIP·제출일 머리글과 SEC 원문 링크가 붙는다.
    """
    from .rag import search

    where = []
    if cusip:
        where.append(f"c.cusip = '{re.sub(r'[^0-9A-Za-z]', '', cusip)}'")
    if product_type:
        where.append(f"p.product_type = '{re.sub(r'[^0-9A-Za-z_]', '', product_type)}'")
    con = _connect()
    try:
        hits = search(con, query, k=min(max(k, 1), 8), where=" AND ".join(where) or None)
        urls = dict(con.execute("SELECT accession_number, url FROM documents").fetchall())
    finally:
        con.close()
    if hits.empty:
        return "(검색 결과 없음)"
    out = []
    for i, h in enumerate(hits.itertuples(), 1):
        text = h.text if len(h.text) <= 900 else h.text[:900] + "…"
        out.append(f"--- 결과 {i} | 출처: {urls.get(h.accession_number, h.accession_number)}\n{text}")
    return "\n\n".join(out)


@server.tool()
def get_product(cusip: str) -> str:
    """CUSIP 하나의 조건(값이 있는 항목만)과 SEC 원문 링크, 관련 공시를 보여 준다."""
    con = _connect()
    try:
        row = con.execute("SELECT * FROM products WHERE cusip = ?", [cusip.strip()]).df()
    finally:
        con.close()
    if row.empty:
        return f"CUSIP {cusip} 상품이 수업 데이터에 없습니다 (예정 발행일 2025-10~2026-09 범위 밖이거나 검토 대기일 수 있음)."
    rec = {k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in row.iloc[0].to_dict().items()
           if v is not None and v == v and k != "product_family"}
    return "```json\n" + json.dumps(rec, ensure_ascii=False, indent=1, default=str) + "\n```"


# ------------------------------------------------------------------ HTTP 앱
@server.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request):
    return PlainTextResponse("ok")


class RateLimit:
    """분당 요청 수 제한 (서버 전체). 커넥터 요청은 Anthropic 서버에서 오므로 IP 별 제한은 의미가 작다."""

    def __init__(self, app, per_minute: int):
        self.app, self.per_minute, self.hits = app, per_minute, deque()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
            now = time.monotonic()
            while self.hits and now - self.hits[0] > 60:
                self.hits.popleft()
            if len(self.hits) >= self.per_minute:
                await JSONResponse({"error": "rate limited, retry in a minute"}, status_code=429)(scope, receive, send)
                return
            self.hits.append(now)
        await self.app(scope, receive, send)


def create_app():
    app = server.streamable_http_app(
        stateless_http=True,  # 세션 없이 요청마다 처리 → 컨테이너가 0개로 줄었다가 다시 떠도 문제없음
        json_response=True,
        # 공개 서버(Azure 도메인)이므로 localhost 전용 DNS rebinding 보호는 끈다. 데이터는 공개 SEC 공시뿐이고 읽기 전용
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    )
    return RateLimit(app, RATE_LIMIT_PER_MIN)


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
