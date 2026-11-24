"""텍스트 v2: SEC 원문 HTML 27,000건 → 평문, 자동 검사, 상품 표 다시 만들기 (강사용).

    uv run python shinhan/tools/text_v2.py check  [--work data/text_v2]   # 검사 1~3 (약 7분)
    uv run python shinhan/tools/text_v2.py build  [--work data/text_v2]   # 변환 + 상품 표 (약 25분)

입력은 Dropbox 수업 자료: 01_SEC_공시_HTML/*.zip (원문 27,000건), 03_분석_출처_검증_수업자료.zip
(상품 표를 만드는 결정적 Python 코드 src/ 와 그 입력 data/). AI 호출은 없다.

'완벽한 변환'의 자동 검사
  검사 1 글자 보존: HTML 화면 글자와 변환 결과에서 공백·'|'를 뺀 글자열이 순서까지 완전히 같다.
  검사 2 숫자 온전함: 날짜·금액·비율이 줄바꿈으로 끊기지 않고, 원문에 없는 공백이 끼지 않는다.
  검사 3 정답 근거: 정답 27건의 근거 인용문(gold/*.json 의 _evidence)이 변환 결과의 한 줄 안에 그대로 있다.
  (검사 4는 사람이 표본을 원문 화면과 나란히 보고 확인한다.)

build 순서
  1) 원문 HTML 을 <work>/shared/raw/documents 에 푼다.
  2) aifinance.htmltext 로 변환 → <work>/text/raw/text (문단·표 구조가 있는 텍스트 v2).
  3) 상품 표 규칙(Dropbox src/)은 한 줄짜리 텍스트에 맞춰져 있으므로, 줄바꿈과 표 칸 구분 ' | ' 만 공백으로
     바꾼 한 줄 판을 <work>/flat/raw/text 에 만든다 (글자는 그대로).
  4) Dropbox src/ 의 extract → product_units → contract_classify → prepare_outputs 를 그대로 돌린다.
     결과: <work>/flat/data/products_in_period.csv 등.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from aifinance.htmltext import convert, is_pdf_layout  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

DBX = Path.home() / "Library/CloudStorage/Dropbox/JPMorgan_424B2_AI_Finance_수업자료"
HTML_ZIPS = DBX / "01_SEC_공시_HTML"
PIPE_ZIP = DBX / "03_분석_출처_검증_수업자료.zip"
GOLD = REPO / "gold"

M = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE_ANY = re.compile(rf"\b{M}\s+\d{{1,2}}\s*,\s*\d{{4}}\b")
DATE_OK = re.compile(rf"{M} \d{{1,2}}, \d{{4}}")
NUM_NL = re.compile(r"\d,[ \t]*\n\s*\d{3}\b|\d\.[ \t]*\n[ \t]*\d+%|\d[ \t]*\n\s*%|\$[ \t]*\n\s*\d")  # '1,⏎000' '10⏎%' '$⏎1'
NUM_SP = re.compile(r"\$ \d|\d [,.]\d|\d[,.] \d{3}\b|\d %")  # 숫자 안의 공백


# ---------------------------------------------------------------- 검사
def _nospace(t: str) -> str:
    return re.sub(r"[\s|]", "", t)


def _collapse(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace(" | ", " ").replace("|", " ")).strip()


def _reference(raw: bytes, spaced: bool = False) -> str:
    """HTML 화면 글자 (검사의 기준). spaced=True 면 <br>·블록 경계를 공백으로 (원문 대조용)."""
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    if spaced:
        for br in soup.find_all("br"):
            br.replace_with(" ")
        for tag in soup.find_all(["p", "div", "td", "th", "tr", "li", "table"]):
            tag.insert_after(" ")
    return soup.get_text("")


def check_one(raw: bytes) -> tuple[dict, str]:
    out = convert(raw)
    res = {"kind": "pdf" if is_pdf_layout(raw.decode("utf-8", "replace")) else "dom", "c1": True, "c2": []}
    a, b = _nospace(_reference(raw)), _nospace(out)
    if a != b:
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        res["c1"] = False
        res["c1_at"] = {"html": a[max(0, i - 40):i + 40], "text": b[max(0, i - 40):i + 40]}
    ref_c = _collapse(_reference(raw, spaced=True))
    for m in DATE_ANY.finditer(out):
        g = m.group()
        if "\n" in g or (not DATE_OK.fullmatch(g) and _collapse(g) not in ref_c):
            res["c2"].append(("date", out[max(0, m.start() - 50):m.end() + 20]))
    for pat, label in [(NUM_NL, "num_newline"), (NUM_SP, "num_space")]:
        for m in pat.finditer(out):
            if label == "num_space":
                pre = out[max(0, m.start() - 12):m.start() + 1]
                if re.search(rf"{M} \d{{0,2}}$", pre) and re.match(r"\d, \d{4}", out[m.start():m.start() + 7]):
                    continue  # 'October 16, 2025' 의 '6, 2' 는 정상 날짜
                ctx = re.sub(r"([●•▪◦■]) ", r"\1", out[max(0, m.start() - 8):m.end() + 8])  # 글머리표 뒤 공백은 변환기가 넣은 것
                if _collapse(ctx) in ref_c:
                    continue  # 원문에도 똑같이 있다
            res["c2"].append((label, out[max(0, m.start() - 50):m.end() + 30]))
    return res, out


_zips: dict[str, zipfile.ZipFile] = {}


def _check_task(task: tuple[str, str]) -> dict:
    zname, member = task
    if zname not in _zips:
        _zips[zname] = zipfile.ZipFile(HTML_ZIPS / zname)
    res, _ = check_one(_zips[zname].read(member))
    res.update(name=member, zip=zname, agent=Path(member).stem[:10])
    return res


def _html_tasks() -> list[tuple[str, str]]:
    tasks = []
    for zp in sorted(HTML_ZIPS.glob("*.zip")):
        with zipfile.ZipFile(zp) as z:
            tasks += [(zp.name, n) for n in z.namelist() if n.endswith((".html", ".htm"))]
    return tasks


def gold_html(acc: str) -> bytes:
    """정답 문서의 원문 HTML: Dropbox 원문 ZIP, 없으면 저장소 data/raw (수집 노트북이 받은 원문)."""
    for zp in sorted(HTML_ZIPS.glob("*.zip")):
        with zipfile.ZipFile(zp) as z:
            n = f"raw/documents/{acc}.html"
            if n in z.namelist():
                return z.read(n)
    a, b, c = acc.split("-")
    hits = sorted((REPO / "data" / "raw").glob(f"{a}{b}{c}_*.htm"))
    if not hits:
        raise FileNotFoundError(acc)
    return hits[0].read_bytes()


def cmd_check(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    tasks = _html_tasks()
    print(f"검사 대상 {len(tasks):,}건", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        results = list(ex.map(_check_task, tasks, chunksize=32))
    c3 = []
    for gp in sorted(GOLD.glob("*.json")):
        g = json.loads(gp.read_text(encoding="utf-8"))
        raw = gold_html(gp.stem)
        _, out = check_one(raw)
        lines = [_collapse(x) for x in out.split("\n") if x.strip()]
        ref_c = _collapse(_reference(raw))
        for field, ev in (g.get("_evidence") or {}).items():
            e = _collapse(ev)
            c3.append({"accession": gp.stem, "field": field, "evidence": ev,
                       "in_html": e in ref_c, "in_one_line": any(e in ln for ln in lines)})
    c1 = sum(not r["c1"] for r in results)
    c2 = sum(bool(r["c2"]) for r in results)
    ev = [c for c in c3 if c["in_html"]]
    summary = {
        "documents": len(results),
        "kinds": {k: sum(r["kind"] == k for r in results) for k in ("dom", "pdf")},
        "check1_failed_documents": c1,
        "check2_failed_documents": c2,
        "check2_defects": sum(len(r["c2"]) for r in results),
        "check3_evidence_in_html": len(ev),
        "check3_found_in_one_line": sum(c["in_one_line"] for c in ev),
        "check3_evidence_not_verbatim_in_html": [c for c in c3 if not c["in_html"]],
        "failures": [r for r in results if not r["c1"] or r["c2"]][:200],
        "seconds": round(time.time() - t0),
    }
    (work / "text_checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"검사 1 글자 보존: 실패 {c1} / {len(results)}")
    print(f"검사 2 숫자 온전함: 실패 {c2} / {len(results)}")
    print(f"검사 3 정답 근거: {summary['check3_found_in_one_line']} / {len(ev)} "
          f"(원문 HTML 에 글자 그대로 없는 인용문 {len(c3) - len(ev)}개는 따로 기록)")
    print(f"→ {work / 'text_checks.json'}  ({summary['seconds']}s)")


# ---------------------------------------------------------------- 변환 + 상품 표
def _convert_file(args: tuple[Path, Path]) -> int:
    src, dst = args
    dst.write_text(convert(src.read_bytes()), encoding="utf-8")
    return 1


def flat_view(text: str) -> str:
    """상품 표 규칙(Dropbox src/)용 한 줄 판: 줄바꿈과 표 칸 구분만 공백으로 (글자는 그대로)."""
    return re.sub(r"\s+", " ", text.replace(" | ", " ")).strip()


def cmd_build(work: Path) -> None:
    docs = work / "shared" / "raw" / "documents"
    if not docs.exists() or len(list(docs.glob("*.html"))) < 27000:
        print("원문 HTML 풀기…", flush=True)
        for zp in sorted(HTML_ZIPS.glob("*.zip")):
            with zipfile.ZipFile(zp) as z:
                z.extractall(work / "shared", [n for n in z.namelist() if n.startswith("raw/documents/")])
    text_dir = work / "text" / "raw" / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    srcs = sorted(docs.glob("*.html"))
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        n = sum(ex.map(_convert_file, [(p, text_dir / f"{p.stem}.txt") for p in srcs], chunksize=32))
    print(f"텍스트 v2 {n:,}건 ({time.time() - t0:.0f}s)", flush=True)

    flat = work / "flat"
    if flat.exists():
        shutil.rmtree(flat)
    (flat / "raw" / "text").mkdir(parents=True)
    (flat / "logs").mkdir()
    os.symlink(docs, flat / "raw" / "documents")
    for p in text_dir.glob("*.txt"):
        (flat / "raw" / "text" / p.name).write_text(flat_view(p.read_text(encoding="utf-8")), encoding="utf-8")
    with zipfile.ZipFile(PIPE_ZIP) as z:
        z.extractall(flat, [m for m in z.namelist() if m.split("/")[0] in ("src", "tests", "data", "qa")])
    env = dict(os.environ, EXTRACT_REUSE_TEXT_AFTER="0")  # 위에서 만든 텍스트를 그대로 쓰게 한다
    for step in ["extract", "product_units", "contract_classify", "prepare_outputs"]:
        print(f"== {step}", flush=True)
        subprocess.run(["uv", "run", "-q", "--python", "3.12", "--with", "beautifulsoup4", "python", f"src/{step}.py"],
                       cwd=flat, env=env, check=True)
    print(f"→ {flat / 'data' / 'products_in_period.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "build"])
    ap.add_argument("--work", type=Path, default=REPO / "data" / "text_v2")
    a = ap.parse_args()
    (cmd_check if a.cmd == "check" else cmd_build)(a.work.resolve())  # 상대 경로면 원문 링크가 깨진다


if __name__ == "__main__":
    main()
