"""실습 키트 공용: .env 읽기, DB 연결, 표 출력. (원본 참고: shinhan/jpm_kit/kit_common.py)

.env 의 값 (비밀 파일. 열거나 출력하지 않는다)
  PGHOST, PGUSER, PGPASSWORD, PGDATABASE   내 Azure PostgreSQL
  SHARED_HOST, SHARED_USER, SHARED_PASSWORD, SHARED_DATABASE   강사의 공용 상품 DB (읽기 전용)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows에서 Claude Code가 실행하면 출력이 cp949가 되어 한글이 깨지거나 일부 기호에서 멈춘다 → UTF-8로 고정
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

KIT = Path(__file__).resolve().parent


def load_env() -> None:
    path = KIT / ".env"
    if not path.exists():
        if (KIT / ".env.txt").exists():
            sys.exit("jpm_kit/.env.txt 가 있습니다. 메모장이 .txt 를 붙여 저장한 것입니다. VS Code 탐색기에서 이름을 .env 로 바꾸세요.")
        sys.exit("jpm_kit/.env 파일이 없습니다. .env.example 을 복사해 .env 로 만들고 값을 채우세요.")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:  # Windows 메모장 ANSI(cp949)
        raw = path.read_text(encoding="cp949", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def connect(prefix: str = "PG"):
    """prefix='PG' 는 내 DB, 'SHARED' 는 공용 상품 DB."""
    import psycopg

    load_env()
    host = os.environ.get(f"{prefix}HOST" if prefix == "PG" else f"{prefix}_HOST", "").strip()
    user = os.environ.get(f"{prefix}USER" if prefix == "PG" else f"{prefix}_USER", "jpmadmin").strip()
    pw = os.environ.get(f"{prefix}PASSWORD" if prefix == "PG" else f"{prefix}_PASSWORD", "")
    db = os.environ.get(f"{prefix}DATABASE" if prefix == "PG" else f"{prefix}_DATABASE", "postgres").strip() or "postgres"
    if not host or not pw or "<" in host:
        sys.exit(f".env 의 {prefix} 접속 정보(호스트·비밀번호)가 비어 있습니다.")
    if "." not in host and host != "localhost":
        host += ".postgres.database.azure.com"  # 서버 이름만 적은 경우
    try:
        return psycopg.connect(host=host, user=user, password=pw, dbname=db, sslmode="require",
                               autocommit=True, connect_timeout=20)
    except psycopg.OperationalError as e:
        msg = str(e).splitlines()[0]
        hint = ""
        if "timeout" in msg.lower() or "no pg_hba" in msg.lower() or "connection refused" in msg.lower():
            hint = "\n→ 방화벽: 포털 → 내 PostgreSQL → 네트워킹 → '현재 클라이언트 IP 주소 추가' → 저장"
        elif "password authentication failed" in msg:
            hint = "\n→ .env 의 비밀번호를 확인하세요 (서버를 만들 때 정한 것)"
        sys.exit(f"DB 연결 실패: {msg}{hint}")


def table(cur, sql: str, params=None) -> str:
    """조회 결과를 마크다운 표로."""
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    rows = cur.fetchall()
    w = [max(len(str(c)), *(len(f"{r[i]:,}" if isinstance(r[i], int) else str(r[i])) for r in rows)) if rows else len(str(c))
         for i, c in enumerate(cols)]
    fmt = lambda vals: "| " + " | ".join(str(v).ljust(w[i]) for i, v in enumerate(vals)) + " |"  # noqa: E731
    out = [fmt(cols), "|" + "|".join("-" * (x + 2) for x in w) + "|"]
    out += [fmt([f"{v:,}" if isinstance(v, int) else v for v in r]) for r in rows]
    return "\n".join(out)


# ------------------------------------------------------------------ Azure OpenAI 임베딩
EMB_DIM = 1536
API_VERSION = "2024-10-21"


class Embedder:
    """글 묶음 → 벡터(숫자 1,536개) 묶음. .env 의 AOAI_ENDPOINT, AOAI_KEY, AOAI_DEPLOYMENT 를 쓴다.
    분당 한도(429)에 걸리면 Azure 가 알려준 시간만큼 기다렸다가 다시 보낸다."""

    def __init__(self):
        import time  # noqa: F401
        import httpx

        load_env()
        ep = os.environ.get("AOAI_ENDPOINT", "").strip().rstrip("/")
        key = os.environ.get("AOAI_KEY", "").strip()
        if not ep or not key or "<" in ep + key:
            sys.exit(".env 의 AOAI_ENDPOINT, AOAI_KEY 를 채워야 임베딩을 쓸 수 있습니다.")
        dep = os.environ.get("AOAI_DEPLOYMENT", "emb3s").strip() or "emb3s"
        self.url = f"{ep}/openai/deployments/{dep}/embeddings?api-version={API_VERSION}"
        self.headers = {"api-key": key}
        self.client = httpx.Client(timeout=120)
        self.tokens = 0
        self.waits = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        import time

        for attempt in range(10):
            try:
                r = self.client.post(self.url, headers=self.headers, json={"input": texts})
            except Exception:  # noqa: BLE001  일시적인 네트워크 오류
                time.sleep(2 ** min(attempt, 5))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                self.waits += 1
                time.sleep(min(60.0, float(r.headers.get("retry-after", 0) or 0) + 2 ** min(attempt, 4)))
                continue
            if r.status_code in (401, 403):
                sys.exit("Azure OpenAI 키가 맞지 않습니다. .env 의 AOAI_KEY 를 확인하세요.")
            if r.status_code == 404:
                sys.exit("임베딩 배포를 찾지 못했습니다. .env 의 AOAI_ENDPOINT 와 AOAI_DEPLOYMENT 를 확인하세요.")
            r.raise_for_status()
            d = r.json()
            self.tokens += d["usage"]["total_tokens"]
            return [e["embedding"] for e in sorted(d["data"], key=lambda e: e["index"])]
        raise RuntimeError("Azure OpenAI 재시도 횟수를 넘었습니다. 잠시 후 다시 실행하세요 (끝난 부분은 건너뜁니다).")


def vec(v) -> str:
    """파이썬 숫자 목록 → pgvector 글자 표기 '[0.01,-0.2,...]'"""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
