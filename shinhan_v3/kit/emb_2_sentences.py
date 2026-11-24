# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "httpx", "psycopg[binary]"]
# ///
"""임베딩 이해하기 ② 문장을 숫자 1,536개로: 내 Azure OpenAI(text-embedding-3-small).

    uv run jpm_kit/emb_2_sentences.py
    uv run jpm_kit/emb_2_sentences.py "내 문장 1" "내 문장 2" "내 문장 3"    # 직접 넣은 문장끼리 비교

보여 주는 것
  1. 같은 단어 bond 라도 문장 속 뜻(채권 / 화학 결합)에 따라 다른 곳에 놓인다 (단어 벡터의 한계를 넘음)
  2. 한국어 질문과 영어 공시 문장이 같은 뜻이면 가깝다 → 키워드 검색은 못 찾는 것을 벡터 검색은 찾는 이유
  3. 숫자가 다른 두 문장은 거의 같은 곳에 놓인다 → 벡터 검색이 정확한 숫자에 약한 이유 (그래서 키워드와 합친다)
비용: 문장 몇 개라 1원도 안 됨.
"""

from __future__ import annotations

import sys

import numpy as np

import kit_db

DEMO = [
    ("채권A", "The notes are unsecured and unsubordinated obligations of JPMorgan Chase Financial Company LLC."),
    ("채권B", "This bond pays a fixed coupon and repays principal at maturity."),
    ("화학", "A covalent bond forms when two atoms share a pair of electrons."),
    ("한국어", "이 상품은 만기에 원금을 돌려주나요? 원금 손실 위험은?"),
    ("손실", "If the Final Value is less than the Trigger Value, you will lose 1% of the principal amount for every 1% decline."),
    ("차감", "The Index is subject to a 6.0% per annum daily deduction, which will offset any appreciation of the futures contracts."),
    ("숫자1", "The Contingent Interest Rate is 10.75% per annum."),
    ("숫자2", "The Contingent Interest Rate is 8.10% per annum."),
]


def main() -> None:
    pairs = [(f"문장{i + 1}", s) for i, s in enumerate(sys.argv[1:])] or DEMO
    emb = kit_db.Embedder()
    E = np.array(emb([s for _, s in pairs]))
    print(f"문장 {len(pairs)}개 → 각각 숫자 {E.shape[1]:,}개 (보낸 토큰 {emb.tokens}개)")
    print(f"예: '{pairs[0][0]}' 의 앞 6개 = {np.round(E[0][:6], 4).tolist()} …\n")
    S = E @ E.T  # 이 모델의 벡터는 길이가 1 → 내적 = 코사인 유사도
    names = [n for n, _ in pairs]
    w = max(len(n) for n in names) + 2
    print("코사인 유사도 (1에 가까울수록 뜻이 비슷)")
    print(" " * w + "".join(f"{n:>8}" for n in names))
    for i, n in enumerate(names):
        print(f"{n:<{w}}" + "".join(f"{S[i, j]:8.2f}" if i != j else f"{'·':>8}" for j in range(len(names))))
    if pairs is DEMO:
        g = {n: i for i, n in enumerate(names)}
        print("\n읽는 법")
        print(f"  채권B–채권A {S[g['채권B'], g['채권A']]:.2f}  vs  채권B–화학 {S[g['채권B'], g['화학']]:.2f}"
              "  → 같은 'bond'라도 문맥이 뜻을 정한다")
        best = max(("채권A", "손실", "차감", "숫자1"), key=lambda n: S[g['한국어'], g[n]])
        print(f"  한국어 질문과 가장 가까운 영어 문장: {best} ({S[g['한국어'], g[best]]:.2f})"
              "  → 단어가 하나도 안 겹쳐도 찾는다")
        print(f"  숫자1–숫자2 {S[g['숫자1'], g['숫자2']]:.2f}  → 10.75%와 8.10%를 거의 구별하지 못한다:"
              " 정확한 숫자·이름은 키워드 검색이 낫다")


if __name__ == "__main__":
    main()
