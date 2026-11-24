"""강사가 받은 10개월 원문(data/sec_v3)에서 학생 검증용 10월 기준표를 만든다.

    uv run python shinhan_v3/tools/make_oct_reference.py

출력: shinhan_v3/kit/data/oct_reference.csv  (accession, filing_date, primary_document, bytes, sha256)
sha256 은 SEC 봇 차단 <script src="/..."> 줄을 뺀 바이트 기준 (check_oct.py 와 같은 방식).
"""

import csv
import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "data" / "sec_v3"
OUT = REPO / "shinhan_v3" / "kit" / "data" / "oct_reference.csv"
BOT_SCRIPT = re.compile(rb'<script type="text/javascript"\s+src="/[^"]*"></script>')
MONTH = "2026-10"

with (SRC / "filings.csv").open(encoding="utf-8") as f:
    rows = [r for r in csv.DictReader(f) if r["month"] == MONTH]
out, missing = [], []
for r in rows:
    p = SRC / "html" / f"{r['accession']}.html"
    if not p.exists():
        missing.append(r["accession"])
        continue
    b = BOT_SCRIPT.sub(b"", p.read_bytes())
    out.append(dict(accession=r["accession"], filing_date=r["filing_date"], primary_document=r["primary_document"],
                    bytes=len(b), sha256=hashlib.sha256(b).hexdigest()))
if missing:
    sys.exit(f"{MONTH} 원문 {len(missing)}건이 아직 없습니다 (다운로드가 끝난 뒤 다시 실행). 예: {missing[:3]}")
OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)
both = sum(";" in r["registrant_ciks"] for r in rows)
print(f"{MONTH} 424B2 {len(out):,}건 (두 CIK 함께 {both:,}, 모회사만 {len(out) - both:,}) → {OUT}")
