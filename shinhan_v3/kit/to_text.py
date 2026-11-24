# /// script
# requires-python = ">=3.10"
# dependencies = ["beautifulsoup4", "lxml"]
# ///
"""내가 받은 10월 원문 HTML(jpm_kit/sec_oct/html)을 텍스트로 바꾸고, 글자를 하나도 잃지 않았는지 검사한다.

    uv run jpm_kit/to_text.py                     # 전체 변환 + 검사
    uv run jpm_kit/to_text.py --show <accession>  # 한 건: HTML 종류, 크기, 변환 결과 앞부분

변환기는 jpm_kit/htmltext.py (강사가 제공, 고치지 않음).
검사: HTML에서 화면에 보이는 글자(태그·스크립트·스타일 제외)와 변환 결과의 글자를,
      공백과 '|' 를 빼고 비교한다. 순서까지 완전히 같아야 통과.
"""

import argparse
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
import htmltext  # noqa: E402

HTML = KIT / "sec_oct" / "html"
TEXT = KIT / "sec_oct" / "text"


def visible_chars(raw: bytes) -> str:
    """검사 기준: 화면에 보이는 글자만 (공백·'|' 제외)."""
    soup = BeautifulSoup(raw, "lxml")
    for t in soup(["script", "style", "head"]):
        t.decompose()
    return re.sub(r"[\s|]", "", soup.get_text(""))


def show(acc: str) -> None:
    p = HTML / f"{acc}.html"
    raw = p.read_bytes()
    s = raw.decode("utf-8", "replace")
    kind = "PDF를 HTML로 바꾼 형식" if htmltext.is_pdf_layout(s) else "일반 HTML(문서 구조)"
    text = htmltext.convert(raw)
    print(f"{acc}: {kind}")
    print(f"HTML {len(raw) / 1024:,.0f}KB → 텍스트 {len(text.encode()) / 1024:,.0f}KB, {text.count(chr(10)) + 1:,}줄")
    print("-" * 60)
    print("\n".join(text.splitlines()[:40]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show")
    a = ap.parse_args()
    if a.show:
        return show(a.show)
    files = sorted(HTML.glob("*.html"))
    if not files:
        sys.exit("jpm_kit/sec_oct/html 에 파일이 없습니다. 먼저 sec_oct.py 로 원문을 받으세요.")
    TEXT.mkdir(parents=True, exist_ok=True)
    kinds = {"pdf": [], "dom": []}
    failed = []
    for i, p in enumerate(files, 1):
        raw = p.read_bytes()
        text = htmltext.convert(raw)
        (TEXT / f"{p.stem}.txt").write_text(text, encoding="utf-8")
        kinds["pdf" if htmltext.is_pdf_layout(raw.decode("utf-8", "replace")) else "dom"].append(p.stem)
        if visible_chars(raw) != re.sub(r"[\s|]", "", text):
            failed.append(p.stem)
        if i % 200 == 0:
            print(f"{i:,}/{len(files):,}", flush=True)
    print(f"\n변환 {len(files):,}건 → jpm_kit/sec_oct/text/")
    print(f"  일반 HTML {len(kinds['dom']):,}건 (예: {kinds['dom'][0] if kinds['dom'] else '-'})")
    print(f"  PDF를 HTML로 바꾼 형식 {len(kinds['pdf']):,}건 (예: {kinds['pdf'][0] if kinds['pdf'] else '-'})")
    print(f"글자 보존 검사: 통과 {len(files) - len(failed):,} / 실패 {len(failed):,}")
    for acc in failed[:5]:
        print("  실패:", acc)


if __name__ == "__main__":
    main()
