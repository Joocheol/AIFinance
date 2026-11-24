# /// script
# requires-python = ">=3.10"
# ///
"""내가 받은 10월 공시(jpm_kit/sec_oct)를 강사가 같은 날 받은 기준과 대조한다.

    uv run jpm_kit/check_oct.py

기준: jpm_kit/data/oct_reference.csv (accession, primary_document, bytes, sha256)
      sha256 은 SEC가 보낼 때마다 바꿔 붙이는 봇 차단 <script src="/..."> 줄을 뺀 바이트의 해시다.
"""

import csv
import hashlib
import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
MINE = KIT / "sec_oct"
REF = KIT / "data" / "oct_reference.csv"
BOT_SCRIPT = re.compile(rb'<script type="text/javascript"\s+src="/[^"]*"></script>')


def norm_sha(b: bytes) -> str:
    return hashlib.sha256(BOT_SCRIPT.sub(b"", b)).hexdigest()


def main() -> None:
    if not REF.exists():
        sys.exit(f"기준 파일이 없습니다: {REF}")
    with REF.open(encoding="utf-8") as f:
        ref = {r["accession"]: r for r in csv.DictReader(f)}
    mine_list = MINE / "filings.csv"
    if not mine_list.exists():
        sys.exit("jpm_kit/sec_oct/filings.csv 가 없습니다. 먼저 sec_oct.py --list-only 를 실행하세요.")
    with mine_list.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    key = next((k for k in (rows[0].keys() if rows else []) if "accession" in k.lower()), None)
    if key is None:
        sys.exit("filings.csv 에 accession 칸이 없습니다.")
    mine = {r[key].strip() for r in rows}

    print("== 목록")
    print(f"강사 기준 {len(ref):,}건 / 내 목록 {len(mine):,}건")
    print(f"같음 {len(mine & ref.keys()):,}  빠짐 {len(ref.keys() - mine):,}  더 있음 {len(mine - ref.keys()):,}")
    for a in sorted(ref.keys() - mine)[:5]:
        print("  빠진 예:", a, ref[a]["primary_document"])
    for a in sorted(mine - ref.keys())[:5]:
        print("  더 있는 예:", a)

    print("\n== 원문")
    same = diff = missing = 0
    diffs = []
    for a, r in sorted(ref.items()):
        p = MINE / "html" / f"{a}.html"
        if not p.exists():
            missing += 1
            continue
        if norm_sha(p.read_bytes()) == r["sha256"]:
            same += 1
        else:
            diff += 1
            diffs.append(a)
    print(f"같음 {same:,}  다름 {diff:,}  없음 {missing:,}  (기준 {len(ref):,}건)")
    for a in diffs[:5]:
        print("  다른 예:", a, "→ 파일을 지우고 sec_oct.py 를 다시 실행해 보세요 (이어 받기)")
    ok = same == len(ref) and mine == ref.keys()
    print("\n결과:", "모두 같습니다." if ok else "다른 곳이 있습니다. 위 목록을 확인하세요.")


if __name__ == "__main__":
    main()
