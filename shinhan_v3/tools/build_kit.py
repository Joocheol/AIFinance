"""AI Finance 1 실습 키트 ZIP 만들기 (강사용).

    uv run python shinhan_v3/tools/build_kit.py [--out 폴더]

입력: shinhan_v3/kit/ (스크립트, CLAUDE.md, README.md, .env.example, data/oct_reference.csv)
출력: <out>/실습키트.zip — 안에는 jpm_kit/ 폴더 하나 (압축을 jpm-class 에 풀면 jpm-class/jpm_kit/)
      .env, sec_oct/, out/, __pycache__ 는 넣지 않는다.
"""

import argparse
import hashlib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "shinhan_v3" / "kit"
DBX = Path.home() / "Library/CloudStorage/Dropbox/JPMorgan_424B2_AI_Finance_수업자료/07_AI_Finance_1"
SKIP_DIRS = {"sec_oct", "out", "__pycache__"}
SKIP_FILES = {".env", ".env.txt", ".DS_Store"}

ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, default=DBX)
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
files = sorted(p for p in KIT.rglob("*") if p.is_file()
               and not (set(p.relative_to(KIT).parts[:-1]) & SKIP_DIRS) and p.name not in SKIP_FILES)
need = {"README.md", "CLAUDE.md", ".env.example", "check_oct.py", "htmltext.py", "to_text.py", "kit_db.py",
        "load_text.py", "shared_products.py", "embed.py", "emb_1_words.py", "emb_2_sentences.py", "ask.py", "similar.py"}
missing = need - {p.name for p in files}
assert not missing, f"빠진 파일: {missing}"
assert (KIT / "data" / "oct_reference.csv").exists(), "data/oct_reference.csv 가 없습니다 (make_oct_reference.py)"
out = a.out / "실습키트.zip"
tmp = out.with_suffix(".part")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, "jpm_kit/" + p.relative_to(KIT).as_posix())
tmp.replace(out)
sha = hashlib.sha256(out.read_bytes()).hexdigest()
print(f"{out}  {out.stat().st_size / 1e6:.1f}MB  파일 {len(files)}개  sha256 {sha[:16]}…")
for p in files:
    print("  jpm_kit/" + p.relative_to(KIT).as_posix())
