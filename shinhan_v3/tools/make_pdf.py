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
@page { size: A4; margin: 16mm 14mm; }
body { font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif; font-size: 10.5pt; line-height: 1.55; color: #14213D; }
h1 { font-size: 17pt; border-bottom: 2px solid #14213D; padding-bottom: 4px; margin-top: 0; }
h2 { font-size: 13.5pt; margin-top: 18px; color: #2B5EA7; }
h3 { font-size: 11.5pt; margin-top: 14px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #C9D2DE; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #E8EDF4; }
code { font-family: 'Menlo', 'Consolas', monospace; font-size: 9pt; background: #F2F4F8; padding: 0 3px; }
pre { background: #F2F4F8; padding: 8px 10px; white-space: pre-wrap; word-break: break-all; font-size: 8.8pt; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { border-left: 4px solid #A8540F; margin: 8px 0; padding: 2px 10px; background: #F7EADC; }
.doc + .doc { page-break-before: always; }
.cover { font-size: 9pt; color: #55606F; margin-bottom: 10px; }
"""


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
        await pg.set_content(page, wait_until="load")
        await pg.pdf(path=out, format="A4", print_background=True,
                     display_header_footer=True, header_template="<span></span>",
                     footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#888'>"
                                     f"{title} · <span class='pageNumber'></span>/<span class='totalPages'></span></div>",
                     margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        await b.close()
    print(out)


asyncio.run(main())
