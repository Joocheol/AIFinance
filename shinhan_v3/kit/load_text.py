# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]"]
# ///
"""내가 바꾼 10월 텍스트(jpm_kit/sec_oct/text)를 내 Azure PostgreSQL 에 넣는다.

    uv run jpm_kit/load_text.py            # 표가 이미 있으면 건너뜀
    uv run jpm_kit/load_text.py --force    # 지우고 다시

만드는 표
  filings (accession, month, chars, body)                       공시 1건 = 1행, 텍스트 전문
  chunks  (chunk_id, accession, seq, is_boilerplate, body, tsv)  검색 단위: 텍스트의 줄(문단·표 행)을 최대 1,200자까지 묶음
          tsv = 키워드 색인용 (영어 형태소). 벡터 칸(emb)은 다음 실습에서 채운다.
상품 표는 넣지 않는다: 강사의 공용 상품 DB 를 읽는다 (shared_products.py).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import re
import time

import kit_db

TEXT = kit_db.KIT / "sec_oct" / "text"
MAX_CHARS = 1200
EMB_DIM = 1536


def units(text: str) -> list[str]:
    """텍스트의 한 줄(문단 하나 또는 표의 한 행)이 한 단위. 글자 2개 미만인 줄은 버린다."""
    return [ln.strip() for ln in text.splitlines() if len(re.findall(r"\w", ln)) >= 2]


def key(u: str) -> str:
    return hashlib.md5(re.sub(r"\W+", " ", u.lower()).strip().encode()).hexdigest()


def boilerplate(texts: dict[str, str], min_share: float = 0.05, min_docs: int = 5) -> set[str]:
    """여러 공시에 똑같이 반복되는 긴 단위(위험 고지 등) = 공통 문구. 검색이 이것으로 도배되지 않게 한 번만 넣는다."""
    seen = collections.Counter()
    for t in texts.values():
        seen.update({key(u) for u in units(t) if len(u) >= 200})
    need = max(min_docs, int(len(texts) * min_share))
    return {k for k, n in seen.items() if n >= need}


def pack(us: list[str], max_chars: int = MAX_CHARS) -> list[str]:
    out, cur = [], ""
    for u in us:
        while len(u) > max_chars:  # 아주 긴 단위는 잘라서
            if cur:
                out.append(cur)
                cur = ""
            out.append(u[:max_chars])
            u = u[max_chars:]
        if cur and len(cur) + 1 + len(u) > max_chars:
            out.append(cur)
            cur = u
        else:
            cur = f"{cur}\n{u}" if cur else u
    if cur:
        out.append(cur)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    files = sorted(TEXT.glob("*.txt"))
    if not files:
        raise SystemExit("jpm_kit/sec_oct/text 가 비어 있습니다. 먼저 to_text.py 를 실행하세요.")
    t_all = time.time()
    con = kit_db.connect()
    cur = con.cursor()
    cur.execute("select exists(select 1 from pg_available_extensions where name='vector')")
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        has_vector = True
    except Exception:  # noqa: BLE001  서버 매개변수 azure.extensions 에 VECTOR 를 허용하지 않은 경우
        has_vector = False
        print("주의: vector 확장을 켤 수 없습니다 (포털 → 서버 매개변수 → azure.extensions 에 VECTOR). 벡터 칸 없이 진행합니다.")
    cur.execute("select to_regclass('filings') is not null and to_regclass('chunks') is not null")
    if cur.fetchone()[0] and not a.force:
        print("filings·chunks 표가 이미 있습니다. 다시 만들려면 --force")
    else:
        texts = {p.stem: p.read_text(encoding="utf-8") for p in files}
        t0 = time.time()
        cur.execute("DROP TABLE IF EXISTS chunks")
        cur.execute("DROP TABLE IF EXISTS filings")
        cur.execute("CREATE TABLE filings (accession text PRIMARY KEY, month text, chars int, body text)")
        with cur.copy("COPY filings (accession, month, chars, body) FROM STDIN") as cp:
            for acc, body in texts.items():
                cp.write_row((acc, "2026-10", len(body), body))
        print(f"filings: {len(texts):,}건 ({sum(map(len, texts.values())) / 1e6:.1f}백만 자, {time.time() - t0:.0f}초)")

        t0 = time.time()
        bp = boilerplate(texts)
        rows, bp_done = [], set()
        for acc, body in sorted(texts.items()):
            own = []
            for u in units(body):
                k = key(u)
                if k in bp:
                    if k not in bp_done:  # 공통 문구는 처음 나온 공시에 한 번만
                        bp_done.add(k)
                        rows.append((acc, True, u[:MAX_CHARS]))
                else:
                    own.append(u)
            rows += [(acc, False, c) for c in pack(own)]
        emb = f", emb vector({EMB_DIM})" if has_vector else ""
        cur.execute(f"""CREATE TABLE chunks (chunk_id int PRIMARY KEY, accession text, seq int, is_boilerplate bool, body text,
                        tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED{emb})""")
        seq = collections.Counter()
        with cur.copy("COPY chunks (chunk_id, accession, seq, is_boilerplate, body) FROM STDIN") as cp:
            for i, (acc, is_bp, body) in enumerate(rows):
                cp.write_row((i, acc, seq[acc], is_bp, body))
                seq[acc] += 1
        cur.execute("CREATE INDEX chunks_tsv ON chunks USING gin(tsv)")
        print(f"chunks: {len(rows):,}개 (공통 문구 {len(bp_done):,}개, 최대 {MAX_CHARS}자) + 키워드 색인 ({time.time() - t0:.0f}초)")
    for t in ("filings", "chunks"):
        cur.execute(f"ANALYZE {t}")  # 행 수 통계 갱신
    print("\n내 DB의 표:")
    print(kit_db.table(cur, """select relname as 표, n_live_tup::int as 행수, pg_size_pretty(pg_total_relation_size(relid)) as 크기
                               from pg_stat_user_tables order by relname"""))
    cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
    print(f"\nDB 전체 {cur.fetchone()[0]} / {time.time() - t_all:.0f}초")


if __name__ == "__main__":
    main()
