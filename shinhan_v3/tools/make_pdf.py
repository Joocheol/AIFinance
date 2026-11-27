# /// script
# requires-python = ">=3.10"
# dependencies = ["markdown", "playwright"]
# ///
"""Markdown 여러 개 → PDF 한 개 (설치된 Chrome 으로 인쇄).

    uv run shinhan_v3/tools/make_pdf.py <출력.pdf> <제목> <a.md> [<b.md> …]
"""

import asyncio
import sys
from pathlib import Path

import markdown
from playwright.async_api import async_playwright

CSS = """
@page { size: A4; }
body { font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif; font-size: 10.5pt; line-height: 1.8; color: #14213D; }
p { margin: 0 0 10px; }
ul, ol { margin: 6px 0 12px; padding-left: 22px; }
li { margin: 4px 0; }
h1 { font-size: 18pt; border-bottom: 2px solid #14213D; padding-bottom: 6px; margin: 0 0 16px; }
h2 { font-size: 14pt; margin: 30px 0 12px; color: #2B5EA7; }
h3 { font-size: 12pt; margin: 22px 0 10px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0 18px; font-size: 9.8pt; line-height: 1.65; }
tr { page-break-inside: avoid; }
td:empty { width: 16%; }
th, td { border: 1px solid #C9D2DE; padding: 7px 10px; vertical-align: top; text-align: left; }
th { background: #E8EDF4; }
td:empty::after { content: "\\00a0"; }
code { font-family: 'Menlo', 'Consolas', monospace; font-size: 9pt; background: #F2F4F8; padding: 1px 4px; border-radius: 3px; }
pre { background: #F2F4F8; padding: 12px 14px; margin: 10px 0 16px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; font-size: 9pt; border-radius: 4px; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
td code { word-break: break-all; }
blockquote { border-left: 4px solid #A8540F; margin: 14px 0 18px; padding: 10px 16px; background: #F7EADC; }
blockquote p { margin: 0 0 8px; } blockquote p:last-child { margin-bottom: 0; }
hr { border: none; border-top: 1px solid #C9D2DE; margin: 24px 0; }
h2, h3 { page-break-after: avoid; }
.doc + .doc { page-break-before: always; }
.cover { font-size: 9pt; color: #55606F; margin-bottom: 10px; }
"""

# A4 본문 영역(210×297mm − 여백 18mm×2)을 CSS px(96dpi)로
PAGE_W, PAGE_H = round(174 / 25.4 * 96), round(261 / 25.4 * 96)
LONG = 0.4   # 소제목 구역이 쪽 높이의 40%보다 길면 새 쪽에서 시작
NEAR = 0.25  # 다만 문서 시작이나 앞의 강제 쪽나눔에서 25% 안쪽이면 그대로

BREAK_JS = """([pageH, long, near]) => {
  let n = 0;
  // 반쪽보다 짧은 표는 쪽 경계에서 나누지 않는다
  for (const t of document.querySelectorAll('table'))
    if (t.getBoundingClientRect().height < 0.5 * pageH) t.style.breakInside = 'avoid';
  for (const doc of document.querySelectorAll('.doc')) {
    const hs = [...doc.querySelectorAll('h2, h3')];
    const top = el => el.getBoundingClientRect().top + window.scrollY;
    const docEnd = top(doc) + doc.getBoundingClientRect().height;
    let last = top(doc);
    hs.forEach((h, i) => {
      // 구역 끝 = 같은 수준 이상의 다음 소제목
      const lvl = +h.tagName[1];
      const nxt = hs.slice(i + 1).find(x => +x.tagName[1] <= lvl);
      const len = (nxt ? top(nxt) : docEnd) - top(h);
      const y = top(h);
      if (len > long * pageH && y - last > near * pageH) {
        h.style.breakBefore = 'page';
        const prev = h.previousElementSibling;
        if (prev && prev.tagName === 'HR') prev.style.display = 'none';
        last = y; n++;
      }
    });
  }
  return n;
}"""

async def main() -> None:
    out, title, *files = sys.argv[1:]
    parts = []
    for f in files:
        md = Path(f).read_text(encoding="utf-8")
        html = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
        parts.append(f'<div class="doc">{html}</div>')
    page = f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page()
        await pg.set_viewport_size({"width": PAGE_W, "height": PAGE_H})
        await pg.emulate_media(media="print")
        await pg.set_content(page, wait_until="load")
        n = await pg.evaluate(BREAK_JS, [PAGE_H, LONG, NEAR])
        print(f"새 페이지에서 시작한 소제목 {n}개")
        await pg.pdf(path=out, format="A4", print_background=True,
                     display_header_footer=True, header_template="<span></span>",
                     footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#888'>"
                                     f"{title} · <span class='pageNumber'></span>/<span class='totalPages'></span></div>",
                     margin={"top": "18mm", "bottom": "18mm", "left": "18mm", "right": "18mm"})
        await b.close()
    print(out)


asyncio.run(main())
