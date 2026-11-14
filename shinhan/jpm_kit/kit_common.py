"""실습 키트 공통 도구: .env 읽기, DB 연결, 청크 나누기, Azure OpenAI 임베딩, 세 가지 검색.

이 파일은 스크립트 01~05가 함께 씁니다. 비밀번호와 키는 .env 에서만 읽고, 화면에 출력하지 않습니다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

KIT = Path(__file__).resolve().parent
DATA = KIT / "data"
OUT = KIT / "out"
MONTH = "2026-09"
EMB_DIM = 1536
API_VERSION = "2024-10-21"

# Windows 콘솔(cp949)에서도 한글·기호가 깨지거나 멈추지 않게
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 설정(.env)
def load_env() -> dict[str, str]:
    """jpm_kit/.env 를 읽어 환경변수로 넣는다. 값은 출력하지 않는다."""
    path = KIT / ".env"
    if not path.exists() and (KIT / ".env.txt").exists():  # Windows 메모장이 확장자를 붙인 경우
        path = KIT / ".env.txt"
        print("알림: .env.txt 를 읽습니다. 메모장이 .txt 를 붙였습니다. 파일 이름을 .env 로 바꾸는 것을 권합니다.", file=sys.stderr)
    if not path.exists():
        sys.exit("오류: jpm_kit/.env 파일이 없습니다. .env.example 을 복사해 이름을 .env 로 바꾸고 네 칸을 채우세요.")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:  # 메모장 ANSI(cp949)로 저장한 경우
        raw = path.read_text(encoding="cp949", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    need = ["PGHOST", "PGPASSWORD"]
    missing = [k for k in need if not os.environ.get(k) or "<" in os.environ[k]]
    if missing:
        sys.exit(f"오류: .env 의 {', '.join(missing)} 칸이 비어 있습니다.")
    return {k: os.environ.get(k, "") for k in ("PGHOST", "PGUSER", "AOAI_ENDPOINT", "AOAI_DEPLOYMENT")}


def connect():
    import psycopg

    load_env()
    host = os.environ["PGHOST"].strip()
    if "." not in host:  # 서버 이름만 적은 경우
        host += ".postgres.database.azure.com"
    try:
        return psycopg.connect(host=host, dbname=os.environ.get("PGDATABASE", "postgres"),
                               user=os.environ.get("PGUSER", "jpmadmin"), password=os.environ["PGPASSWORD"],
                               sslmode="require", autocommit=True, connect_timeout=20)
    except psycopg.OperationalError as e:
        msg = str(e)
        hint = ""
        if "password authentication failed" in msg:
            hint = "→ .env 의 PGPASSWORD 가 배포할 때 정한 DB 비밀번호와 같은지 확인하세요."
        elif "no pg_hba.conf entry" in msg or "timeout" in msg.lower() or "could not connect" in msg:
            hint = ("→ DB 방화벽이 지금 내 공인 IP를 허용하지 않습니다. Azure 포털 → jpm-pg-… → 네트워킹 → "
                    "'현재 클라이언트 IP 주소 추가' → 저장 후 다시 실행하세요.")
        sys.exit(f"DB 연결 실패: {msg.splitlines()[0][:200]}\n{hint}")


def sql_table(cur, sql: str, params=None) -> str:
    """SELECT 결과를 마크다운 표 문자열로."""
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    rows = cur.fetchall()
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c)) for i, c in enumerate(cols)]
    line = lambda vals: "| " + " | ".join(str(v).ljust(w[i]) for i, v in enumerate(vals)) + " |"  # noqa: E731
    return "\n".join([line(cols), "|" + "|".join("-" * (x + 2) for x in w) + "|", *map(line, rows)])


# ------------------------------------------------------------------ 청크 나누기
MAX_CHARS = 1200  # 청크 최대 길이(문자). 실험 B에서 바꿔 봅니다.


def paragraphs(text: str) -> list[str]:
    """문단 단위로 나눈다. 줄바꿈이 거의 없는 한 줄짜리 정규화 텍스트는 문장 단위로 나눈다."""
    if text.count("\n") < 5 and len(text) > 5000:
        units = re.split(r"(?<=[.;])\s+(?=[A-Z●•“\"(])", re.sub(r"\s+", " ", text))
        return [u.strip() for u in units if len(u.strip()) >= 20]
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if len(p) >= 40]


def _key(p: str) -> str:
    # 페이지 표기('PS-3')만 지우고 해시. 숫자까지 지우면 상품별 조건 줄이 공통 문구로 잘못 묶인다.
    return hashlib.md5(re.sub(r"\b(?:PS|US|TS)-\s?\d+\b", "", p.lower()).encode()).hexdigest()


def find_boilerplate(texts: list[str], min_share: float = 0.05, min_docs: int = 5) -> set[str]:
    """여러 문서(5% 이상)에 반복되는 문장의 키 집합 = 공통 문구."""
    counts = Counter(k for t in texts for k in {_key(p) for p in paragraphs(t)})
    threshold = max(min_docs, int(len(texts) * min_share))
    return {k for k, n in counts.items() if n >= threshold}


def pack(paras: list[str], max_chars: int = MAX_CHARS) -> list[str]:
    """문장을 max_chars 이내로 이어 붙인다."""
    chunks, cur = [], ""
    for p in paras:
        pieces = [p] if len(p) <= max_chars else re.split(r"(?<=[.;])\s+", p)
        for piece in pieces:
            if cur and len(cur) + len(piece) + 1 > max_chars:
                chunks.append(cur)
                cur = ""
            cur = f"{cur} {piece}".strip() if cur else piece[: max_chars * 2]
    if cur:
        chunks.append(cur)
    return chunks


def make_chunks(texts: dict[str, str], max_chars: int = MAX_CHARS, headers: dict[str, str] | None = None) -> list[tuple]:
    """(accession, seq, is_boilerplate, body) 목록.

    - 문서마다 고유한 문장은 그 문서의 청크로
    - 여러 문서에 반복되는 공통 문구는 처음 나온 문서 기준으로 한 번만 (중복 색인 방지)
    - headers 를 주면 문서 고유 청크 앞에 한 줄 머리글을 붙인다 (실험 A)
    """
    bp_keys = find_boilerplate(list(texts.values()))
    rows, seen_bp = [], {}
    for acc, text in texts.items():
        specific = []
        for p in paragraphs(text):
            if _key(p) in bp_keys:
                seen_bp.setdefault(_key(p), (acc, p))
            else:
                specific.append(p)
        head = (headers or {}).get(acc)
        for i, c in enumerate(pack(specific, max_chars)):
            rows.append((acc, i, False, f"{head}\n{c}" if head else c))
    by_acc: dict[str, list[str]] = {}
    for acc, p in seen_bp.values():
        by_acc.setdefault(acc, []).append(p)
    for acc, ps in by_acc.items():
        for i, c in enumerate(pack(ps, max_chars)):
            rows.append((acc, i, True, c))
    return rows


def read_month_texts() -> dict[str, str]:
    folder = DATA / f"filings_{MONTH}"
    files = sorted(folder.glob("*.txt"))
    if not files:
        sys.exit(f"오류: {folder} 에 공시 텍스트가 없습니다. 실습 키트 ZIP을 다시 풀어 주세요.")
    return {f.stem: f.read_text(encoding="utf-8", errors="replace") for f in files}


# ------------------------------------------------------------------ Azure OpenAI 임베딩
class Embedder:
    def __init__(self):
        import httpx

        load_env()
        ep = os.environ.get("AOAI_ENDPOINT", "").strip().rstrip("/")
        key = os.environ.get("AOAI_KEY", "").strip()
        if not ep or not key or "<" in ep + key:
            sys.exit("오류: .env 의 AOAI_ENDPOINT, AOAI_KEY 칸을 채워야 벡터 검색을 쓸 수 있습니다.")
        dep = os.environ.get("AOAI_DEPLOYMENT", "emb3s").strip() or "emb3s"
        self.url = f"{ep}/openai/deployments/{dep}/embeddings?api-version={API_VERSION}"
        self.headers = {"api-key": key}
        self.client = httpx.Client(timeout=120)
        self.tokens = 0
        self.waits = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(10):
            try:
                r = self.client.post(self.url, headers=self.headers, json={"input": texts})
            except Exception:  # noqa: BLE001  네트워크 일시 오류
                time.sleep(2 ** min(attempt, 5))
                continue
            if r.status_code == 429 or r.status_code >= 500:  # 분당 한도 초과 → 서버가 알려준 만큼 기다렸다 다시
                self.waits += 1
                time.sleep(min(60.0, float(r.headers.get("retry-after", 0) or 0) + 2 ** min(attempt, 4)))
                continue
            if r.status_code in (401, 403):
                sys.exit("오류: Azure OpenAI 키가 맞지 않습니다. .env 의 AOAI_KEY 를 포털의 '키 1'로 다시 붙여 넣으세요.")
            if r.status_code == 404:
                sys.exit("오류: 임베딩 배포(emb3s)를 찾지 못했습니다. .env 의 AOAI_ENDPOINT 를 확인하세요.")
            r.raise_for_status()
            d = r.json()
            self.tokens += d["usage"]["total_tokens"]
            return [e["embedding"] for e in sorted(d["data"], key=lambda e: e["index"])]
        raise RuntimeError("Azure OpenAI 재시도 횟수를 넘었습니다. 잠시 후 다시 실행하세요 (끝난 부분은 건너뜁니다).")


def vec_literal(v) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


# ------------------------------------------------------------------ 검색 세 가지
def search_keyword(cur, query: str, k: int = 10, table: str = "chunks") -> list[tuple[int, str]]:
    """PostgreSQL 전문 검색. 모든 단어가 들어간 청크를 먼저 찾고, 없으면 단어 중 하나라도 들어간 청크."""
    cur.execute(f"""SELECT chunk_id, body FROM {table}, websearch_to_tsquery('english', %s) q
                    WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC, chunk_id LIMIT %s""", (query, k))
    rows = cur.fetchall()
    if not rows:
        cur.execute(f"""SELECT chunk_id, body FROM {table},
                        to_tsquery('english', array_to_string(tsvector_to_array(to_tsvector('english', %s)), ' | ')) q
                        WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC, chunk_id LIMIT %s""", (query, k))
        rows = cur.fetchall()
    return rows


def search_vector(cur, qvec, k: int = 10, table: str = "chunks") -> list[tuple[int, str]]:
    """pgvector 코사인 거리로 가장 가까운 청크."""
    cur.execute("SET hnsw.ef_search = 100")
    cur.execute(f"SELECT chunk_id, body FROM {table} WHERE emb IS NOT NULL ORDER BY emb <=> %s::vector LIMIT %s",
                (vec_literal(qvec), k))
    return cur.fetchall()


def fuse(lists: list[list[tuple[int, str]]], k: int = 10, weights: list[float] | None = None, rrf_k: int = 60):
    """순위 융합(RRF): 각 목록에서 r위인 청크에 weight/(60+r) 점을 더해 합산 순위로."""
    weights = weights or [1.0] * len(lists)
    score: dict[int, list] = {}
    for w, lst in zip(weights, lists):
        for r, (cid, body) in enumerate(lst):
            score.setdefault(cid, [0.0, body])[0] += w / (rrf_k + r + 1)
    return [(c, s[1]) for c, s in sorted(score.items(), key=lambda kv: -kv[1][0])[:k]]


def load_questions() -> list[dict]:
    path = DATA / "eval" / "retrieval_questions.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def is_hit(body: str, q: dict) -> bool:
    b = body.lower()
    return any(p.lower() in b for p in q["relevant_phrases"])


FIELDS = {"query": "영어 원래 질문", "query_paraphrase": "바꿔 말한 영어", "query_ko": "한국어 그대로",
          "query_rewritten": "한국어 → 영어 검색어"}
