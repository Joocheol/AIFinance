"""신한은행 수업용 MCP 서버 — 수강생 자신의 Azure Database for PostgreSQL 을 읽는다.

    PGHOST=... PGUSER=... PGPASSWORD=... uv run python -m aifinance.pg_server     # http://0.0.0.0:8000/mcp

환경변수
- PGHOST / PGPORT / PGDATABASE                         : 수강생 DB
- PGADMIN_USER / PGADMIN_PASSWORD / PGREADER_PASSWORD  : 처음 한 번 읽기 전용 계정(mcp_reader)을 만드는 데만 쓴다
  (또는 PGUSER / PGPASSWORD 로 이미 있는 읽기 전용 계정을 바로 지정)
- AOAI_ENDPOINT / AOAI_KEY / AOAI_DEPLOYMENT          : 검색어 임베딩용 Azure OpenAI (없으면 키워드 검색만)

DB 구조 (수업 활동에서 수강생이 만든다)
- products    : 12개월 전체 상품 표 (상품 1개 = 1행, 강사 배포)
- filings     : 내가 적재한 공시 원문 (accession, month, body)
- chunks      : 원문 청크 (tsv = 키워드 색인, emb = vector(1536) 의미 색인)
- my_products : 내가 추출한 상품 표 (선택)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque

import httpx
import pandas as pd
import psycopg
import psycopg.sql
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

MAX_ROWS = int(os.getenv("MAX_ROWS", "50"))
MAX_CELL = 160
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))
AOAI_ENDPOINT = os.getenv("AOAI_ENDPOINT", "").rstrip("/")
AOAI_KEY = os.getenv("AOAI_KEY", "")
AOAI_DEPLOYMENT = os.getenv("AOAI_DEPLOYMENT", "emb3s")

INSTRUCTIONS = """\
JP Morgan 구조화 노트 수업 데이터입니다. 수강생이 자신의 Azure PostgreSQL 에 직접 만든 DB 입니다.
- products: 예정 발행일 2025-10-01~2026-09-30 상품 10,410개 (상품 1개 = 1행)
- filings / chunks: 수강생이 적재한 공시 원문과 그 청크 (키워드 색인 + 벡터 색인)

도구 선택:
- 숫자·집계·비교 → query_products (PostgreSQL SQL). 처음에는 describe_database 로 컬럼 뜻과 단위를 확인하세요.
- 조건의 의미·위험·계산 방식 → search_filings. 공시가 영어이므로 검색어는 424B2 공시 용어(영어)로 바꿔서 쓰세요.
- 상품 하나의 조건을 원문으로 확인할 때는 get_product 의 accession 을 search_filings(accession=...) 에 넣어 그 공시 안에서만 찾으세요.
- 특정 상품 → get_product(cusip).

반드시 지킬 규칙:
- *_pct 컬럼은 퍼센트포인트입니다 (coupon_annual_pct = 10.75 → 연 10.75%).
- 결측(NULL)은 0 이 아닙니다. 합계·평균을 낼 때 몇 개가 비어 있는지 함께 밝히세요.
- 공시 건수와 상품 수를 구분하세요. 한 공시에 상품이 여러 개일 수 있습니다.
- price_value_gap_pct(발행가격과 최초 추정가치의 차이)는 발행사 순이익이 아닙니다. '가격·가치 차이'라고 부르세요.
- product_type 은 '계약조건 근거 규칙 분류(잠정)'이며 사람 전수 검토 전입니다.
- 근거가 된 CUSIP 과 SEC 원문 링크를 밝히고, 확인하지 못한 것은 '확인하지 못함'이라고 쓰세요.
"""

server = MCPServer(name="jpm-424b2-my-postgres", instructions=INSTRUCTIONS)


READER = os.getenv("PGREADER_USER", "mcp_reader")
_bootstrapped = False


def _bootstrap() -> None:
    """배포 직후 한 번: 관리자 계정(PGADMIN_*)으로 읽기 전용 계정을 만들고, 이후 모든 도구는 그 계정으로만 접속한다.

    수강생이 나중에 관리자 계정으로 만드는 표도 자동으로 읽을 수 있게 기본 권한을 걸어 둔다.
    """
    global _bootstrapped
    if _bootstrapped or not os.getenv("PGADMIN_USER"):
        _bootstrapped = True
        return
    pw = os.environ["PGREADER_PASSWORD"]
    with psycopg.connect(user=os.environ["PGADMIN_USER"], password=os.environ["PGADMIN_PASSWORD"],
                         sslmode=os.getenv("PGSSLMODE", "require"), connect_timeout=15, autocommit=True) as a:
        exists = a.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER,)).fetchone()
        a.execute(psycopg.sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            psycopg.sql.SQL("ALTER" if exists else "CREATE"), psycopg.sql.Identifier(READER), psycopg.sql.Literal(pw)))
        db = os.getenv("PGDATABASE", "postgres")
        for stmt in ("GRANT CONNECT ON DATABASE {db} TO {r}", "GRANT USAGE ON SCHEMA public TO {r}",
                     "GRANT SELECT ON ALL TABLES IN SCHEMA public TO {r}",
                     "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {r}"):
            a.execute(psycopg.sql.SQL(stmt).format(db=psycopg.sql.Identifier(db), r=psycopg.sql.Identifier(READER)))
    os.environ["PGUSER"], os.environ["PGPASSWORD"] = READER, pw
    _bootstrapped = True


def _connect() -> psycopg.Connection:
    _bootstrap()
    conn = psycopg.connect(sslmode=os.getenv("PGSSLMODE", "require"), connect_timeout=15, autocommit=True)
    conn.execute("SET default_transaction_read_only = on")
    conn.execute("SET statement_timeout = '20s'")
    return conn


def _df(conn: psycopg.Connection, sql: str, params=None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _clip(v):
    if isinstance(v, str) and len(v) > MAX_CELL:
        return v[:MAX_CELL] + "…"
    return v


def _table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(결과 없음)"
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(_clip)
    return df.to_markdown(index=False, floatfmt=".4g")


def _sec_link(accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/19617/{accession.replace('-', '')}/"


def _embed(text: str) -> list[float] | None:
    if not (AOAI_ENDPOINT and AOAI_KEY):
        return None
    r = httpx.post(f"{AOAI_ENDPOINT}/openai/deployments/{AOAI_DEPLOYMENT}/embeddings?api-version=2024-10-21",
                   headers={"api-key": AOAI_KEY}, json={"input": [text]}, timeout=30)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


@server.tool()
def describe_database() -> str:
    """내 DB 의 테이블·컬럼 구조와 행 수, 컬럼 설명(있으면)을 보여 준다. SQL 을 쓰기 전에 먼저 호출하라."""
    with _connect() as conn:
        tables = _df(conn, """SELECT table_name AS 테이블,
                                     (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I', table_name), false, true, '')))[1]::text::bigint AS 행수
                              FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1""")
        has_dd = "data_dictionary" in set(tables["테이블"])
        cols = _df(conn, f"""SELECT c.table_name AS 테이블, c.column_name AS 컬럼, c.data_type AS 타입
                               {", coalesce(left(d.description_ko, 70), '') AS 설명, coalesce(d.csv_unit, '') AS 단위" if has_dd else ""}
                             FROM information_schema.columns c
                             {"LEFT JOIN data_dictionary d ON d.field = c.column_name" if has_dd else ""}
                             WHERE c.table_schema = 'public' AND c.table_name <> 'data_dictionary' AND c.column_name NOT IN ('tsv', 'emb')
                             ORDER BY c.table_name, c.ordinal_position""")
    return "### 테이블과 행 수\n" + _table(tables) + "\n\n### 컬럼 (chunks 의 tsv·emb 색인 컬럼은 생략)\n" + cols.to_markdown(index=False)


FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO|SET|RESET|VACUUM|LISTEN|NOTIFY|pg_\w*sleep|dblink\w*|lo_\w+)\b", re.I)


@server.tool()
def query_products(sql: str) -> str:
    """읽기 전용 SQL(PostgreSQL 문법) 한 문장을 실행한다. 테이블: products, filings, chunks, my_products. 최대 50행.

    예: SELECT product_type, count(*) AS n, round(avg(coupon_annual_pct)::numeric, 2) AS 평균쿠폰 FROM products GROUP BY 1 ORDER BY n DESC
    """
    stmt = sql.strip().rstrip(";")
    if ";" in stmt or not re.match(r"^\s*(SELECT|WITH)\b", stmt, re.I) or FORBIDDEN.search(stmt):
        return "오류: SELECT 또는 WITH 로 시작하는 읽기 전용 쿼리 한 문장만 실행할 수 있습니다."
    try:
        with _connect() as conn:
            df = _df(conn, f"SELECT * FROM ({stmt}) AS q LIMIT {MAX_ROWS + 1}")
    except psycopg.Error as e:
        return f"SQL 오류: {str(e)[:500]}"
    df = df.drop(columns=[c for c in ("emb", "tsv", "body") if c in df.columns])
    note = f"\n\n(처음 {MAX_ROWS}행만 표시했습니다. 집계나 LIMIT 를 쓰세요.)" if len(df) > MAX_ROWS else ""
    return _table(df.head(MAX_ROWS)) + note


@server.tool()
def search_filings(query: str, k: int = 5, mode: str = "hybrid", accession: str = "") -> str:
    """내가 적재한 공시 원문 청크를 검색한다. 검색어는 공시 용어(영어)로 쓴다.

    mode: 'keyword'(PostgreSQL 전문 검색), 'vector'(pgvector 의미 검색), 'hybrid'(둘을 순위 융합, 기본값)
    accession: 상품 하나의 조건을 확인할 때는 get_product 가 알려 준 accession(예: 0001839882-26-045035)을 넣어
               그 공시 안에서만 찾는다. 같은 기초자산의 다른 상품 공시와 섞이지 않게 하려면 반드시 지정한다.
               (여러 공시에 반복되는 공통 문구는 처음 나온 공시에만 들어 있으므로 지정하면 빠질 수 있다.)
    """
    k = min(max(k, 1), 8)
    mode = mode if mode in ("keyword", "vector", "hybrid") else "hybrid"
    acc = accession.strip()
    with _connect() as conn:
        if acc and not _df(conn, "SELECT 1 FROM chunks WHERE accession = %s LIMIT 1", (acc,)).shape[0]:
            return f"accession {acc} 의 원문이 내 DB에 없습니다. 내 DB에는 적재한 달(9월)의 공시만 있습니다. SEC 링크로 직접 확인하세요."
        where = "AND accession = %s" if acc else ""
        kw = vec = pd.DataFrame(columns=["chunk_id", "accession", "body"])
        if mode in ("keyword", "hybrid"):
            kw = _df(conn, f"""SELECT chunk_id, accession, body FROM chunks,
                                to_tsquery('english', array_to_string(tsvector_to_array(to_tsvector('english', %s)), ' | ')) q
                              WHERE tsv @@ q {where} ORDER BY ts_rank_cd(tsv, q) DESC, chunk_id LIMIT 50""",
                     (query, acc) if acc else (query,))
        if mode in ("vector", "hybrid"):
            v = _embed(query)
            if v is None and mode == "vector":
                return "벡터 검색을 쓰려면 서버에 AOAI_ENDPOINT, AOAI_KEY 를 설정해야 합니다."
            if v is not None:
                lit = "[" + ",".join(f"{x:.6f}" for x in v) + "]"
                if acc:  # 공시 하나 안에서는 색인 없이 정확히 계산한다 (청크 수십 개)
                    vec = _df(conn, """WITH d AS MATERIALIZED (SELECT chunk_id, accession, body, emb FROM chunks WHERE accession = %s)
                                       SELECT chunk_id, accession, body FROM d ORDER BY emb <=> %s::vector LIMIT 50""", (acc, lit))
                else:
                    conn.execute("SET hnsw.ef_search = 100")
                    vec = _df(conn, "SELECT chunk_id, accession, body FROM chunks ORDER BY emb <=> %s::vector LIMIT 50", (lit,))
    score: dict[int, list] = {}
    for lst in (kw, vec):
        for r, row in enumerate(lst.itertuples()):
            score.setdefault(row.chunk_id, [0.0, row.accession, row.body])[0] += 1 / (60 + r + 1)
    top = sorted(score.values(), key=lambda s: -s[0])[:k]
    if not top:
        return "(검색 결과 없음)"
    out = []
    for i, (_, acc, body) in enumerate(top, 1):
        text = body if len(body) <= 900 else body[:900] + "…"
        out.append(f"--- 결과 {i} | accession {acc} | 출처: {_sec_link(acc)}\n{text}")
    return f"(검색 방식: {mode})\n\n" + "\n\n".join(out)


@server.tool()
def get_product(cusip: str) -> str:
    """CUSIP 하나의 조건(값이 있는 항목만)과 SEC 원문 링크를 보여 준다."""
    with _connect() as conn:
        row = _df(conn, "SELECT * FROM products WHERE cusip = %s", (cusip.strip().upper(),))
    if row.empty:
        return f"CUSIP {cusip} 상품이 products 표에 없습니다."
    rec = {k: (v.isoformat()[:10] if hasattr(v, "isoformat") else v) for k, v in row.iloc[0].to_dict().items()
           if v is not None and v == v and k != "product_family"}
    return "```json\n" + json.dumps(rec, ensure_ascii=False, indent=1, default=str) + "\n```"


@server.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request):
    return PlainTextResponse("ok")


class RateLimit:
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
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False), host="0.0.0.0")
    return RateLimit(app, RATE_LIMIT_PER_MIN)


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
