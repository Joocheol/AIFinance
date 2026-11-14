# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]>=3.2", "httpx>=0.27"]
# ///
"""활동 3·6 — 청크를 내 Azure OpenAI(text-embedding-3-small)로 벡터화해 chunks.emb 에 저장하고, 벡터 색인(HNSW)을 만든다.

- 보내는 것: 청크 본문(최대 6,000자) 256개씩 묶음 → 받는 것: 청크마다 1,536개 숫자(벡터)
- 분당 한도(TPM)에 걸리면(HTTP 429) Azure가 알려준 시간만큼 기다렸다가 자동으로 다시 보냅니다.
- 이어 하기: 이미 벡터가 있는 청크는 건너뜁니다. 중간에 멈춰도 다시 실행하면 남은 것만 합니다.
- 비용: text-embedding-3-small 은 100만 토큰당 $0.02. 9월 한 달(약 1,100만 토큰) ≈ $0.22

실행: uv run jpm_kit/04_embed.py              (진행 상황은 out/embed_progress.txt 에도 기록)
      uv run jpm_kit/04_embed.py --table chunks_a  (실험용 청크 표)
"""

from __future__ import annotations

import argparse
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import kit_common as kc

ap = argparse.ArgumentParser()
ap.add_argument("--table", default="chunks")
ap.add_argument("--batch", type=int, default=256)
ap.add_argument("--workers", type=int, default=4)
args = ap.parse_args()
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", args.table):
    raise SystemExit("표 이름은 영문 소문자·숫자·밑줄만 쓸 수 있습니다.")
tbl = args.table
kc.OUT.mkdir(exist_ok=True)
log_path = kc.OUT / "embed_progress.txt"


def log(msg: str):
    print(msg, flush=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


emb = kc.Embedder()
conn = kc.connect()
cur = conn.cursor()
cur.execute(f"SELECT count(*), count(emb) FROM {tbl}")
total, done0 = cur.fetchone()
cur.execute(f"SELECT chunk_id, left(body, 6000) FROM {tbl} WHERE emb IS NULL ORDER BY chunk_id")
todo = cur.fetchall()
log(f"[{tbl}] 전체 {total:,}개 중 이미 벡터 있음 {done0:,}개, 이번에 할 것 {len(todo):,}개")

batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
local = threading.local()
lock = threading.Lock()
state = {"done": 0, "last": 0.0}
t0 = time.time()


def work(batch):
    vecs = emb([t for _, t in batch])
    if not hasattr(local, "conn"):
        local.conn = kc.connect()
    with local.conn.cursor() as k:
        k.execute("CREATE TEMP TABLE IF NOT EXISTS e (chunk_id int, emb vector(1536)) ON COMMIT DELETE ROWS")
        with local.conn.transaction():
            with k.copy("COPY e FROM STDIN") as cp:
                for (cid, _), v in zip(batch, vecs):
                    cp.write_row((cid, kc.vec_literal(v)))
            k.execute(f"UPDATE {tbl} c SET emb = e.emb FROM e WHERE c.chunk_id = e.chunk_id")
    with lock:
        state["done"] += len(batch)
        now = time.time()
        if now - state["last"] > 30 or state["done"] == len(todo):
            state["last"] = now
            el = now - t0
            rate = state["done"] / el if el else 0
            eta = (len(todo) - state["done"]) / rate if rate else 0
            log(f"  {done0 + state['done']:,}/{total:,} ({(done0 + state['done']) / total:.0%})  "
                f"경과 {el / 60:.1f}분, 남은 시간 약 {eta / 60:.0f}분, 토큰 {emb.tokens:,}, 한도 대기 {emb.waits}회")


if batches:
    with ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(work, batches))
    log(f"벡터화 완료: {len(todo):,}개, {(time.time() - t0) / 60:.1f}분, 토큰 {emb.tokens:,} (비용 약 ${emb.tokens / 1e6 * 0.02:.2f})")

cur.execute(f"SELECT count(*) FILTER (WHERE emb IS NULL) FROM {tbl}")
left = cur.fetchone()[0]
if left:
    log(f"아직 벡터가 없는 청크 {left:,}개 → 다시 실행하면 이어서 합니다.")
    raise SystemExit(1)

cur.execute("SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexname = %s", (tbl, f"{tbl}_emb_hnsw"))
if cur.fetchone():
    log("벡터 색인(HNSW)이 이미 있습니다.")
else:
    t1 = time.time()
    log("벡터 색인(HNSW) 만드는 중… (몇 분 걸립니다)")
    cur.execute("SET maintenance_work_mem = '256MB'")
    cur.execute(f"CREATE INDEX {tbl}_emb_hnsw ON {tbl} USING hnsw (emb vector_cosine_ops)")
    log(f"벡터 색인 완료 ({(time.time() - t1) / 60:.1f}분)")
cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
log(f"DB 크기 {cur.fetchone()[0]}. 다음: 05_eval_all.py 로 키워드·벡터·하이브리드를 비교합니다.")
