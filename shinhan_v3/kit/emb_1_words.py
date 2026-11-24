# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "matplotlib"]
# ///
"""임베딩 이해하기 ① 단어를 숫자 200개로: 가까운 단어, 단어 계산, 그리고 한계.

    uv run jpm_kit/emb_1_words.py                 # 전부
    uv run jpm_kit/emb_1_words.py --near bank     # 한 단어의 이웃
    uv run jpm_kit/emb_1_words.py --calc king man woman    # king - man + woman = ?

자료: 위키백과 글로 학습한 word2vec 단어 벡터 1만 개 × 숫자 200개
      (TensorFlow Embedding Projector 공개 자료, 약 8MB, 처음 한 번만 받아 jpm_kit/out/ 에 저장)
AI 호출 없음. 계산은 모두 이 노트북에서 numpy 로.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.request import urlopen

import numpy as np

OUT = Path(__file__).resolve().parent / "out"
BASE = ("https://raw.githubusercontent.com/tensorflow/"
        "embedding-projector-standalone/master/oss_data/word2vec_10000_200d_")


def load() -> tuple[list[str], np.ndarray]:
    OUT.mkdir(exist_ok=True)
    lab, ten = OUT / "w2v_labels.tsv", OUT / "w2v_tensors.bytes"
    for name, path in (("labels.tsv", lab), ("tensors.bytes", ten)):
        if not path.exists():
            with urlopen(BASE + name, timeout=60) as f:
                path.write_bytes(f.read())
    words = [row.split("\t")[0] for row in lab.read_text(encoding="utf-8").splitlines()[1:]]  # 첫 줄은 머리글
    V = np.frombuffer(ten.read_bytes(), dtype="<f4").reshape(-1, 200)
    assert len(words) == len(V)
    return words, V


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--near")
    ap.add_argument("--calc", nargs=3, metavar=("A", "B", "C"))
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args()
    words, V = load()
    idx = {w: i for i, w in enumerate(words)}
    N = V / np.linalg.norm(V, axis=1, keepdims=True)  # 길이를 1로: 이제 내적 = 코사인 유사도

    def cos(x: str, y: str) -> float:
        return float(N[idx[x]] @ N[idx[y]])

    def near(w: str, k: int = 6) -> None:
        if w not in idx:
            print(f"'{w}' 는 단어 1만 개 안에 없습니다.")
            return
        s = N @ N[idx[w]]
        s[idx[w]] = -np.inf
        print(f"{w:10} → " + ", ".join(f"{words[i]} {s[i]:.2f}" for i in np.argsort(-s)[:k]))

    def calc(x: str, y: str, z: str, k: int = 4) -> None:
        q = V[idx[x]] - V[idx[y]] + V[idx[z]]  # 벡터 산술
        s = N @ (q / np.linalg.norm(q))
        s[[idx[x], idx[y], idx[z]]] = -np.inf  # 식에 쓴 세 단어는 후보에서 뺀다
        print(f"{x} - {y} + {z} = " + ", ".join(f"{words[i]} {s[i]:.2f}" for i in np.argsort(-s)[:k]))

    if a.near:
        return near(a.near)
    if a.calc:
        return calc(*a.calc)

    print("① 단어 하나 = 숫자 200개")
    print(f"   'bank' 의 앞 8개: {np.round(V[idx['bank']][:8], 3).tolist()} … (모두 200개)")
    print("   숫자 하나하나에는 뜻이 없습니다. 비슷한 문맥에 나오는 단어끼리 숫자 묶음이 비슷해지도록 학습한 결과입니다.\n")

    print("② 가까운 단어 (코사인 유사도: 1에 가까울수록 같은 방향)")
    for w in ("dollar", "loan", "risk", "bank"):
        near(w)

    print("\n③ 단어 계산: 관계도 방향으로 들어 있다")
    for t in (("king", "man", "woman"), ("paris", "france", "japan"), ("china", "chinese", "japan")):
        calc(*t)
    print("   늘 되는 것은 아닙니다:")
    calc("bigger", "big", "good")

    print("\n④ 한계: 단어 하나에 숫자 묶음이 하나뿐 → 뜻이 여럿인 단어는 섞인다")
    near("bond")
    near("interest")
    print(f"   bank–loan {cos('bank', 'loan'):.3f}  vs  bank–river {cos('bank', 'river'):.3f}")
    print("   위키백과에서는 bond 가 '화학 결합'으로 더 많이 쓰여 채권 뜻이 묻힙니다.")
    print("   → 공시 검색에는 문장 전체(앞뒤 문맥)를 보고 숫자로 바꾸는 임베딩을 씁니다: emb_2_sentences.py\n")

    if not a.no_plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        groups = {"나라": ["france", "japan", "china", "italy", "germany", "india"],
                  "수도": ["paris", "tokyo", "beijing", "rome", "berlin", "delhi"],
                  "금융": ["bank", "loan", "debt", "dollar", "currency", "credit"],
                  "화학": ["hydrogen", "molecule", "atom", "carbon", "bond", "acid"]}
        ws = [w for g in groups.values() for w in g if w in idx]
        X = V[[idx[w] for w in ws]]
        X = X - X.mean(0)
        P = X @ np.linalg.svd(X, full_matrices=False)[2][:2].T  # 200차원 → 2차원 (주성분)
        plt.rcParams["font.family"] = ["AppleGothic", "Malgun Gothic", "NanumGothic", "DejaVu Sans"]
        fig, ax = plt.subplots(figsize=(8, 6))
        for g, gw in groups.items():
            pts = [(P[ws.index(w)], w) for w in gw if w in ws]
            ax.scatter([p[0][0] for p in pts], [p[0][1] for p in pts], label=g)
            for p, w in pts:
                ax.annotate(w, p, fontsize=10, xytext=(3, 3), textcoords="offset points")
        ax.legend()
        ax.set_title("숫자 200개를 2차원으로 눌러 본 단어 지도")
        path = OUT / "word_map.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"⑤ 단어 지도: {path}  (비슷한 단어끼리 모이고, 나라→수도 방향이 비슷한지 보세요)")

        # ⑥ 왕·여왕·남자·여자: 축 두 개를 '뜻'으로 정해 그린다 (TensorFlow Projector 의 CUSTOM 투영과 같은 방법)
        pairs = [("man", "woman"), ("king", "queen"), ("prince", "princess"), ("father", "mother"),
                 ("boy", "girl"), ("husband", "wife"), ("brother", "sister"), ("emperor", "empress")]
        unit = lambda v: v / np.linalg.norm(v)  # noqa: E731
        x_axis = unit(N[idx["woman"]] - N[idx["man"]])                                   # 남자 → 여자
        royal = (N[idx["king"]] + N[idx["queen"]]) / 2 - (N[idx["man"]] + N[idx["woman"]]) / 2
        y_axis = unit(royal - (royal @ x_axis) * x_axis)                                 # 보통 사람 → 왕족 (x 와 직각)
        fig, ax = plt.subplots(figsize=(8, 6))
        for m, f in pairs:
            pm = (N[idx[m]] @ x_axis, N[idx[m]] @ y_axis)
            pf = (N[idx[f]] @ x_axis, N[idx[f]] @ y_axis)
            hi = (m, f) in (("man", "woman"), ("king", "queen"))
            ax.annotate("", xy=pf, xytext=pm,
                        arrowprops=dict(arrowstyle="->", color="#A8540F" if hi else "#9AA9C2", lw=2 if hi else 1))
            for p, w in ((pm, m), (pf, f)):
                ax.scatter(*p, color="#14213D" if hi else "#55606F", s=30 if hi else 14)
                ax.annotate(w, p, fontsize=12 if hi else 9, xytext=(4, 4), textcoords="offset points",
                            fontweight="bold" if hi else "normal")
        ax.set_xlabel("남자 → 여자 방향 (woman − man)")
        ax.set_ylabel("보통 사람 → 왕족 방향")
        ax.set_title("king − man + woman ≈ queen: 같은 '남→여' 화살표가 왕족에도 있다")
        path2 = OUT / "king_queen.png"
        fig.savefig(path2, dpi=150, bbox_inches="tight")
        print(f"⑥ 왕·여왕·남자·여자 그림: {path2}  (man→woman 화살표와 king→queen 화살표가 같은 방향인지 보세요)")


if __name__ == "__main__":
    main()
