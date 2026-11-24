# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]", "httpx"]
# ///
"""chunks 의 글을 내 Azure OpenAI(text-embedding-3-small)로 벡터로 바꿔 chunks.emb 에 넣고, 벡터 색인을 만든다.

    uv run jpm_kit/embed.py            # 이어 하기: 벡터가 이미 있는 청크는 건너뛴다
    uv run jpm_kit/embed.py --try 3    # 청크 3개만 보내 보고, 돌아온 숫자의 모양을 보여 준다

보내는 것: 청크 글 256개씩 묶음 → 받는 것: 청크마다 숫자 1,536개.
비용: 100만 토큰당 $0.02 (9월 한 달 약 1,200만 토큰 ≈ $0.24). 분당 한도에 걸리면 자동으로 기다린다.
진행 기록: jpm_kit/out/embed_progress.txt
"""

from __future__ import annotations

import argparse
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import kit_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--try", dest="n_try", type=int, default=0)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    emb = kit_db.Embedder()
    con = kit_db.connect()
    cur = con.cursor()

    if a.n_try:
        cur.execute("select chunk_id, accession, left(body, 300) from chunks where not is_boilerplate order by chunk_id limit %s", (a.n_try,))
        rows = cur.fetchall()
        vecs = emb([r[2] for r in rows])
        for (cid, acc, body), v in zip(rows, vecs):
            print(f"\n청크 {cid} ({acc}): {body[:100]}…")
            print(f"  → 숫자 {len(v)}개: [{', '.join(f'{x:+.4f}' for x in v[:6])}, …]  길이 {math.sqrt(sum(x * x for x in v)):.3f}")
        if len(vecs) >= 2:
            sim = sum(x * y for x, y in zip(vecs[0], vecs[1]))
            print(f"\n청크 {rows[0][0]}와 {rows[1][0]}의 코사인 유사도: {sim:.3f}  (1에 가까울수록 뜻이 비슷)")
        print(f"보낸 토큰 {emb.tokens:,}개")
        return

    out = kit_db.KIT / "out"
    out.mkdir(exist_ok=True)
    log_path = out / "embed_progress.txt"

    def log(msg: str) -> None:
        print(msg, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")

    cur.execute("select count(*), count(emb) from chunks")
    total, done0 = cur.fetchone()
    cur.execute("select chunk_id, left(body, 6000) from chunks where emb is null order by chunk_id")
    todo = cur.fetchall()
    log(f"전체 {total:,}개 중 이미 벡터 있음 {done0:,}개, 이번에 할 것 {len(todo):,}개")
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    local, lock = threading.local(), threading.Lock()
    state = {"done": 0, "last": 0.0}
    t0 = time.time()

    def work(batch):
        vecs = emb([t for _, t in batch])
        if not hasattr(local, "con"):
            local.con = kit_db.connect()
        with local.con.cursor() as k:
            k.execute(f"create temp table if not exists e (chunk_id int, emb vector({kit_db.EMB_DIM})) on commit delete rows")
            with local.con.transaction():
                with k.copy("copy e from stdin") as cp:
                    for (cid, _), v in zip(batch, vecs):
                        cp.write_row((cid, kit_db.vec(v)))
                k.execute("update chunks c set emb = e.emb from e where c.chunk_id = e.chunk_id")
        with lock:
            state["done"] += len(batch)
            now = time.time()
            if now - state["last"] > 30 or state["done"] == len(todo):
                state["last"] = now
                el = now - t0
                eta = (len(todo) - state["done"]) / (state["done"] / el) if el else 0
                log(f"  {done0 + state['done']:,}/{total:,} ({(done0 + state['done']) / total:.0%})  경과 {el / 60:.1f}분, "
                    f"남은 시간 약 {eta / 60:.0f}분, 토큰 {emb.tokens:,}, 한도 대기 {emb.waits}회")

    if batches:
        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(work, batches))
        log(f"벡터화 완료: {len(todo):,}개, {(time.time() - t0) / 60:.1f}분, 토큰 {emb.tokens:,} (약 ${emb.tokens / 1e6 * 0.02:.2f})")
    cur.execute("select count(*) filter (where emb is null) from chunks")
    if cur.fetchone()[0]:
        raise SystemExit("아직 벡터가 없는 청크가 있습니다 → 다시 실행하면 이어서 합니다.")
    cur.execute("select 1 from pg_indexes where indexname = 'chunks_emb_hnsw'")
    if not cur.fetchone():
        t1 = time.time()
        log("벡터 색인(HNSW) 만드는 중…")
        cur.execute("set maintenance_work_mem = '256MB'")
        cur.execute("create index chunks_emb_hnsw on chunks using hnsw (emb vector_cosine_ops)")
        log(f"벡터 색인 완료 ({(time.time() - t1) / 60:.1f}분)")
    cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
    log(f"DB 크기 {cur.fetchone()[0]}")


if __name__ == "__main__":
    main()
