"""10개월(2026-01~10) 공시 텍스트로 상품 표를 만든다 (강사용, AI 호출 없음).

    uv run python shinhan_v3/tools/products_v3.py

입력
  data/sec_v3/filings.csv, html/, text/   (sec_collect.py, to_text.py 결과)
  Dropbox 03_분석_출처_검증_수업자료.zip 의 src/ (상품 표 규칙: extract → product_units → contract_classify → prepare_outputs)
바꾸는 것 (규칙 자체는 그대로)
  - 입력 목록: 2025-10~2026-09 수집 목록 대신 새 19,285건 (data/filings_unique.csv 를 새로 씀), 경계 자료 없음
  - 상품 범위: 예정 발행일 2025-10-01~2026-09-30 → **제출일 2026-01-01~2026-10-31** (받은 공시 기간과 같게)
  - 텍스트: 규칙은 한 줄 텍스트에 맞춰져 있어 v2 텍스트의 줄바꿈과 ' | ' 만 공백으로 바꾼 한 줄 판을 넣는다 (글자는 그대로)
결과: data/sec_v3/pipe/data/products_in_period.csv 등
"""

import csv
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "data" / "sec_v3"
WORK = SRC / "pipe"
PIPE_ZIP = Path.home() / "Library/CloudStorage/Dropbox/JPMorgan_424B2_AI_Finance_수업자료/03_분석_출처_검증_수업자료.zip"
START, END = "2026-01-01", "2026-10-31"


def flat_view(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" | ", " ")).strip()


def patch(path: Path, old: str, new: str) -> None:
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"{path.name}: 바꿀 곳을 찾지 못함: {old[:60]}"
    path.write_text(s.replace(old, new), encoding="utf-8")


def main() -> None:
    t0 = time.time()
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "raw" / "text").mkdir(parents=True)
    (WORK / "logs").mkdir()
    os.symlink(SRC / "html", WORK / "raw" / "documents")
    with zipfile.ZipFile(PIPE_ZIP) as z:
        z.extractall(WORK, [m for m in z.namelist() if m.split("/")[0] in ("src", "tests", "data", "qa")])

    # 1) 입력 목록을 새 19,285건으로
    with (SRC / "filings.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fields = ["accession", "filing_date", "month", "form", "registrant_ciks", "primary_document", "primary_document_url",
              "index_url", "source_files", "collection_status", "document_class", "issuer", "guarantor",
              "source_retrieved_at_utc", "source_sha256", "source_bytes", "raw_local_file", "last_attempt_at_utc",
              "last_http_status", "collection_method", "collection_missing_reason", "cache_check_status"]
    out = []
    for r in rows:
        acc = r["accession"]
        out.append({k: "" for k in fields} | dict(
            accession=acc, filing_date=r["filing_date"], month=r["month"], form="424B2", registrant_ciks=r["registrant_ciks"],
            primary_document=r["primary_document"], primary_document_url=r["url"],
            index_url=r["url"].rsplit("/", 1)[0] + f"/{acc}-index.html",
            source_files=";".join(f"CIK{c}.json" for c in r["registrant_ciks"].split(";")),
            collection_status="downloaded", raw_local_file=f"raw/documents/{acc}.html"))
    for name, data in (("filings_unique.csv", out), ("sample_plan.csv", [])):
        with (WORK / "data" / name).open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields + (["registrant_stratum", "stratum_N", "stratum_n", "selection_probability", "selection_rule"] if name == "sample_plan.csv" else []))
            w.writeheader()
            w.writerows(data)
    (WORK / "data" / "boundary_filings_unique.csv").unlink(missing_ok=True)

    # 2) 상품 범위: 제출일 기준 (규칙 코드의 기간 두 곳)
    src = WORK / "src"
    patch(src / "prepare_outputs.py", "'2025-10-01'<=r.get('issue_date','')<='2026-09-30'", f"'{START}'<=r.get('filing_date','')<='{END}'")
    patch(src / "contract_classify.py", "'2025-10-01'<=r['issue_date']<='2026-09-30'", f"'{START}'<=r['filing_date']<='{END}'")
    patch(src / "prepare_outputs.py", "supplemental=read('boundary_filings_unique.csv');enrich_inventory(supplemental,have,byacc,events,audit);write_csv(ROOT/'data/supplemental_filings_with_status.csv',supplemental)",
          "supplemental=[]  # 경계 자료 없음 (shinhan_v3)")

    # 3) 한 줄 텍스트
    for p in (SRC / "text").glob("*.txt"):
        (WORK / "raw" / "text" / p.name).write_text(flat_view(p.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"준비 {len(out):,}건 ({time.time() - t0:.0f}s)", flush=True)

    env = dict(os.environ, EXTRACT_REUSE_TEXT_AFTER="0")  # 위 텍스트를 그대로 쓴다 (원문을 다시 변환하지 않음)
    for step in ["extract", "product_units", "contract_classify", "prepare_outputs"]:
        print(f"== {step}", flush=True)
        subprocess.run(["uv", "run", "-q", "--python", "3.12", "--with", "beautifulsoup4", "python", f"src/{step}.py"],
                       cwd=WORK, env=env, check=True)
    print(f"→ {WORK / 'data' / 'products_in_period.csv'}  ({(time.time() - t0) / 60:.1f}분)")


if __name__ == "__main__":
    main()
