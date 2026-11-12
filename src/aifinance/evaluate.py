"""추출 결과를 정답셋과 필드 단위로 비교한다."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import PROJECT_ROOT
from .schema import FIELD_GROUPS, TermSheet

GOLD_DIR = PROJECT_ROOT / "gold"
EVAL_FIELDS = [f for fields in FIELD_GROUPS.values() for f in fields if f != "product_name"]


def load_gold(gold_dir: Path = GOLD_DIR) -> dict[str, TermSheet]:
    out = {}
    for p in sorted(Path(gold_dir).glob("*.json")):
        d = json.loads(p.read_text())
        d.pop("_evidence", None)
        out[d["accession_number"]] = TermSheet.model_validate(d)
    return out


def _same(field: str, a, b) -> bool:
    if field == "underlyings":  # 개수와 유형 구성만 비교 (이름 표기는 문서마다 달라서)
        return sorted(u.kind for u in a) == sorted(u.kind for u in b)
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().upper() == b.strip().upper()
    return a == b


def compare(preds: dict[str, TermSheet], gold: dict[str, TermSheet]) -> pd.DataFrame:
    """행 = (문서, 필드). 'outcome' 은 correct / wrong / missed(놓침) / spurious(헛추출)."""
    rows = []
    for acc, g in gold.items():
        p = preds.get(acc)
        for f in EVAL_FIELDS:
            gv, pv = getattr(g, f), getattr(p, f) if p else None
            empty_g = gv in (None, [])
            empty_p = pv in (None, [])
            if empty_g and empty_p:
                outcome = "correct"
            elif empty_p:
                outcome = "missed"
            elif empty_g:
                outcome = "spurious"
            else:
                outcome = "correct" if _same(f, pv, gv) else "wrong"
            rows.append({"accession_number": acc, "field": f, "gold": gv, "pred": pv, "outcome": outcome})
    return pd.DataFrame(rows)


def field_accuracy(cmp: pd.DataFrame) -> pd.DataFrame:
    tbl = pd.crosstab(cmp.field, cmp.outcome)
    for c in ["correct", "wrong", "missed", "spurious"]:
        if c not in tbl:
            tbl[c] = 0
    tbl = tbl[["correct", "wrong", "missed", "spurious"]]
    tbl["accuracy"] = (tbl.correct / tbl.sum(axis=1)).round(3)
    return tbl.loc[[f for f in EVAL_FIELDS if f in tbl.index]]
