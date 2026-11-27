# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "psycopg[binary]", "httpx"]
# ///
"""공시끼리 뜻으로 비교하기: 공시 한 건 = 벡터 하나 (공통 문구가 아닌 청크 벡터의 평균).

    uv run jpm_kit/similar.py --outliers 5                 # 다른 어떤 공시와도 덜 닮은 공시 5건
    uv run jpm_kit/similar.py --text "영어 상품 설명" --text "비교할 다른 설명"   # 새 상품 설명과 가장 비슷한 공시
    uv run jpm_kit/similar.py --like 0001213900-26-112830   # 이 공시와 가장 비슷한 공시

처음 한 번 내 DB에서 공시 벡터 1,859개를 만들어 jpm_kit/out/doc_vectors.npz 에 저장한다(약 30초).
상품 이름·종류는 공용 상품 DB(products)에서 가져온다. 상품 표에 없는 공시(예비 설명서 등)는 '(상품 표에 없음)'.
--text 는 내 Azure OpenAI 로 벡터를 만든다(문장 몇 개라 1원도 안 듦). 한국어 설명은 영어 공시와 잘 비교되지 않으니 영어로 쓴다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_db  # noqa: E402

CACHE = Path(__file__).resolve().parent / "out" / "doc_vectors.npz"


def doc_vectors() -> tuple[list[str], np.ndarray]:
    if CACHE.exists():
        z = np.load(CACHE)
        return list(z["acc"]), z["X"]
    print("공시 벡터 만드는 중 (처음 한 번, 약 30초)…", flush=True)
    with kit_db.connect() as c:
        rows = c.execute("select accession, avg(emb)::text from chunks "
                         "where not is_boilerplate and emb is not null group by accession order by accession").fetchall()
    if not rows:
        sys.exit("chunks 에 벡터가 없습니다. 먼저 uv run jpm_kit/embed.py 를 끝내세요.")
    acc = [a for a, _ in rows]
    X = np.array([np.array(v.strip("[]").split(","), dtype=np.float32) for _, v in rows])
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    CACHE.parent.mkdir(exist_ok=True)
    np.savez(CACHE, acc=np.array(acc), X=X)
    return acc, X


def products() -> dict[str, tuple]:
    with kit_db.connect("SHARED") as c:
        rows = c.execute("select distinct on (accession) accession, cusip, product_type, title from products "
                         "where filing_date between '2026-10-01' and '2026-10-31' order by accession, cusip").fetchall()
    return {a: (cu, pt, ti) for a, cu, pt, ti in rows}


def label(P: dict, a: str) -> str:
    if a not in P:
        return "(상품 표에 없음)"
    cu, pt, ti = P[a]
    return f"{cu} {pt} | {' '.join((ti or '').split())[:90]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outliers", type=int, metavar="N")
    ap.add_argument("--text", action="append", metavar="설명")
    ap.add_argument("--like", metavar="ACCESSION")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    if not (a.outliers or a.text or a.like):
        ap.print_help()
        return
    acc, X = doc_vectors()
    P = products()
    print(f"공시 {len(acc):,}건 (상품 표에 있는 것 {sum(x in P for x in acc):,}건)")

    if a.outliers:
        S = X @ X.T
        np.fill_diagonal(S, -1)
        nn, who = S.max(1), S.argmax(1)
        print(f"\n== 가장 닮은 다른 공시와의 유사도: 중앙값 {np.median(nn):.4f}, "
              f"0.99 이상 {(nn >= 0.99).sum():,}건 ({(nn >= 0.99).mean():.1%}), 최소 {nn.min():.4f}")
        print(f"== 덜 닮은 공시 {a.outliers}건 (유사도가 낮을수록 특이)")
        for i in np.argsort(nn)[: a.outliers]:
            print(f"  {nn[i]:.4f}  {acc[i]}  {label(P, acc[i])}")
            print(f"          가장 닮은 공시: {acc[who[i]]}  {label(P, acc[who[i]])}")

    if a.like:
        if a.like not in acc:
            sys.exit(f"{a.like} 가 내 DB 에 없습니다.")
        s = X @ X[acc.index(a.like)]
        print(f"\n== {a.like}  {label(P, a.like)}\n   와 가장 비슷한 공시 {a.k}건")
        for j in [j for j in np.argsort(-s) if acc[j] != a.like][: a.k]:
            print(f"  {s[j]:.4f}  {acc[j]}  {label(P, acc[j])}")

    if a.text:
        emb = kit_db.Embedder()
        E = np.array(emb(a.text), dtype=np.float32)
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        summary = []
        for n, (t, e) in enumerate(zip(a.text, E), 1):
            s = X @ e
            top = np.argsort(-s)[: a.k]
            print(f"\n== 설명 {n}: {' '.join(t.split())[:100]}…")
            for j in top:
                print(f"  {s[j]:.4f}  {acc[j]}  {label(P, acc[j])}")
            summary.append((n, s[top[0]], s[top].mean(), np.median(s)))
        print("\n== 요약 (1위 유사도가 낮을수록 기존 공시에 닮은 것이 없다)")
        print("  설명 | 1위    | 상위 평균 | 전체 중앙값")
        for n, m, t5, md in summary:
            print(f"  {n:>4} | {m:.4f} | {t5:.4f}    | {md:.4f}")
        print(f"(보낸 토큰 {emb.tokens}개)")


if __name__ == "__main__":
    main()
