# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.1"]
# ///
"""수강생용 실습 키트 ZIP(v2)을 만든다 (강사용).

입력: 저장소 shinhan/jpm_kit 코드 + Dropbox 정규화 텍스트·9월 HTML 목록 + gold/ + eval/ + data/shinhan_jpm.duckdb
출력: <out>/수강생용_실습키트_v2.zip — 안에는 jpm_kit/ 폴더 하나 (압축을 jpm-class 에 풀면 jpm-class/jpm_kit/)

실행: uv run shinhan/build_kit_zip.py [--out 폴더]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
KIT_SRC = REPO / "shinhan" / "jpm_kit"
DBX = Path.home() / "Library/CloudStorage/Dropbox/JPMorgan_424B2_AI_Finance_수업자료"
MONTH = "2026-09"

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(DBX))
args = ap.parse_args()

tmp = Path(tempfile.mkdtemp())
kit = tmp / "jpm_kit"
shutil.copytree(KIT_SRC, kit, ignore=shutil.ignore_patterns(".env", "out", "data", "__pycache__", ".gitignore"))
data = kit / "data"
(data / f"filings_{MONTH}").mkdir(parents=True)
(data / "gold").mkdir()
(data / "gold_texts").mkdir()
(data / "eval").mkdir()

# 1) 9월 공시 목록 = Dropbox main_2026-09.zip 의 accession
with zipfile.ZipFile(DBX / "01_SEC_공시_HTML" / f"main_{MONTH}.zip") as z:
    month_accs = sorted({Path(n).stem for n in z.namelist() if n.endswith(".html")})
gold_accs = sorted(p.stem for p in (REPO / "gold").glob("*.json"))
with zipfile.ZipFile(DBX / "02_정규화텍스트_27000.zip") as z:
    names = {Path(n).stem: n for n in z.namelist() if n.endswith(".txt")}
    missing = [a for a in month_accs if a not in names]
    for a in month_accs:
        if a in names:
            (data / f"filings_{MONTH}" / f"{a}.txt").write_bytes(z.read(names[a]))
    src_note = []
    for a in gold_accs:  # 정규화 텍스트에 없는 정답 문서는 저장소 텍스트를 한 줄로 펴서 쓴다
        if a in names:
            (data / "gold_texts" / f"{a}.txt").write_bytes(z.read(names[a]))
            src_note.append(f"{a}\tDropbox 정규화 텍스트")
        else:
            flat = re.sub(r"\s+", " ", (REPO / "data" / "text" / f"{a}.txt").read_text(encoding="utf-8")).strip()
            (data / "gold_texts" / f"{a}.txt").write_text(flat, encoding="utf-8")
            src_note.append(f"{a}\tSEC 원문 HTML → 텍스트(공백을 한 칸으로)")
    (data / "gold_texts" / "SOURCES.tsv").write_text("accession\tsource\n" + "\n".join(src_note) + "\n", encoding="utf-8")
print(f"9월 공시 {len(month_accs)}건 중 텍스트 {len(month_accs) - len(missing)}건 (없음 {len(missing)})")

# 2) 정답·검색 문항
for p in (REPO / "gold").glob("*.json"):
    shutil.copy(p, data / "gold" / p.name)
qlines = [l for l in (REPO / "eval" / "retrieval_questions.jsonl").read_text(encoding="utf-8").splitlines()
          if l.strip() and json.loads(l).get("cusip") is None]  # 일반 질문 20개 (특정 상품 질문은 9월 범위 밖이 많아 제외)
(data / "eval" / "retrieval_questions.jsonl").write_text("\n".join(qlines) + "\n", encoding="utf-8")

# 3) 상품 표
con = duckdb.connect(str(REPO / "data" / "shinhan_jpm.duckdb"), read_only=True)
typemap = {"VARCHAR": "text", "DATE": "date", "DOUBLE": "double precision", "BIGINT": "bigint",
           "INTEGER": "integer", "BOOLEAN": "boolean"}
desc = con.execute("DESCRIBE products").fetchall()
(data / "products_schema.json").write_text(json.dumps({c: typemap.get(t, "text") for c, t, *_ in desc}, indent=1), encoding="utf-8")
con.execute(f"COPY products TO '{data / 'products.csv'}' (HEADER, DELIMITER ',')")
n_products = con.execute("SELECT count(*) FROM products").fetchall()[0][0]

# 4) 먼저 읽기
(kit / "README_먼저읽기.txt").write_text(f"""JPM 424B2 AI Finance 실습 키트 v2 (신한은행 FE/RM 과정)

jpm-class 폴더는 Mac·Windows 모두 문서(Documents) 폴더 안에 만듭니다.
이 폴더(jpm_kit)가 jpm-class 폴더 바로 안에 있어야 합니다:  문서/jpm-class/jpm_kit/README.md
  - Windows: ZIP을 마우스 오른쪽 → 모두 압축 풀기 → 대상 폴더를 jpm-class 로 지정
  - Mac: ZIP을 더블클릭해 생긴 jpm_kit 폴더를 jpm-class 안으로 옮기기

들어 있는 것
  - 9월 공시 {len(month_accs) - len(missing):,}건, 정답 {len(gold_accs)}건과 원문, 검색 문항 {len(qlines)}개, 상품 표 {n_products:,}개
  - 실습 스크립트 01~05 (사용법: README.md)
  - project_knowledge/ : 2일차 Claude 프로젝트에 올릴 파일 2개

비밀번호와 키는 .env 파일에만 적습니다 (.env.example 참고). 채팅에 붙여 넣지 않습니다.
""", encoding="utf-8")

# 5) 압축 (파일 목록 해시 기록)
out = Path(args.out) / "수강생용_실습키트_v2.zip"
files = sorted(p for p in kit.rglob("*") if p.is_file())
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p in files:
        z.write(p, p.relative_to(tmp).as_posix())
h = hashlib.sha256(out.read_bytes()).hexdigest()
print(f"{out}  {out.stat().st_size / 1e6:.1f}MB  파일 {len(files)}개  sha256 {h[:16]}…")
shutil.rmtree(tmp)
