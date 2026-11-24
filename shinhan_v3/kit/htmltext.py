# /// script
# requires-python = ">=3.10"
# dependencies = ["beautifulsoup4", "lxml"]
# ///
# 실습 키트용 사본. 원본: AIFinance 저장소 src/aifinance/htmltext.py (강사가 27,000건 검사로 확인한 변환기).
# 이 파일은 고치지 않습니다. 무엇을 하는지는 실습지 "HTML을 텍스트로 바꾸기"를 보세요.
"""SEC 공시 HTML → 평문 변환기 (텍스트 v2).

    from aifinance.htmltext import convert
    text = convert(html_bytes)

원칙 ('완벽한 변환'의 정의는 shinhan/tools/text_checks.py 의 검사 1~3)
1. 원문 글자를 바꾸지 않는다. 공백 정리(연속 공백·&nbsp; → 공백 하나)만 한다.
2. 구조를 살린다. 문단은 줄로, 표는 한 행을 '항목 | 값' 한 줄로.
3. HTML 종류별 처리:
   - 일반 HTML(<p>, <table>): 문서 구조(DOM) 그대로.
   - PDF를 HTML로 바꾼 것(pdf2htmlEX, 글자 줄마다 position:absolute): 좌표로
     같은 높이의 조각은 한 행으로, 줄 간격이 보통이면 같은 문단으로 다시 잇는다.
"""

from __future__ import annotations

import re
from statistics import median

from bs4 import BeautifulSoup, NavigableString, Tag

BLOCK_TAGS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "ul", "ol", "center"]
BULLETS = "●•▪◦·■–"
# 문장이 끝나지 않았다는 표시: 쉼표·여는 괄호·하이픈, 또는 뒤에 말이 이어져야 하는 낱말
CONT_END = r"(?:[,(\-–]|\b(?:and|or|of|the|to|a|an|in|on|for|by|with|at|from|than|per|is|are|be|which|that|about|as|if|its|their|our|your|each|any|no|not|such))$"


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def is_pdf_layout(raw: str) -> bool:
    return 'class="pf ' in raw and len(re.findall(r'<div class="t ', raw[:400_000])) >= 5


# ------------------------------------------------------------------ 일반 HTML
def _cell_text(cell: Tag) -> str:
    for br in cell.find_all("br"):
        br.replace_with(" ")
    for t in cell.find_all(BLOCK_TAGS):
        t.insert_before(" ")
        t.insert_after(" ")
    return _squash(cell.get_text(""))  # 인라인 조각 사이에 공백을 끼우지 않는다


MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"


def _near_text(node: Tag, forward: bool, n: int = 40) -> str:
    """<br> 앞(또는 뒤)의 화면 글자 n자. 같은 블록 안에서만 본다."""
    out, el = "", node
    while len(out.strip()) < n:
        el = el.next_element if forward else el.previous_element
        if el is None or (isinstance(el, Tag) and el.name in BLOCK_TAGS + ["td", "th", "tr", "br"]):
            break
        if type(el) is NavigableString:
            out = out + str(el) if forward else str(el) + out
    return _squash(out)


def _br_inside_phrase(br: Tag) -> bool:
    """줄바꿈(<br>)이 문장·날짜·숫자 한가운데에 있으면 화면 배치를 위한 줄바꿈으로 보고 공백으로 바꾼다."""
    before, after = _near_text(br, False), _near_text(br, True)
    if not before or not after:
        return False
    return bool(re.search(CONT_END + "|" + MONTHS + "$|\\d$", before) or re.match(r"[a-z0-9%]", after))


DOM_WIDE_PX = 60.0  # 이보다 넓은 빈 상자 = 다른 항목 사이의 빈칸 (보통 글자 크기 8~12pt의 5배 이상)


def dom_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    # HTML 소스의 줄바꿈은 화면에서 공백일 뿐이다 (<pre> 제외). 줄은 아래에서 블록 경계에만 넣는다.
    for s in list(soup.find_all(string=True)):
        if type(s) is not NavigableString:  # 주석(<!-- -->)·CDATA 등은 화면 글자가 아니다
            continue
        if s.find_parent("pre") is None and re.search(r"[\r\n\t]", s):
            s.replace_with(NavigableString(re.sub(r"[\r\n\t]+", " ", str(s))))
    # 폭을 지정한 빈 상자(display:inline-block; width:400pt)는 화면에서 넓은 빈칸이다: 좌우로 떨어진 항목 사이
    for el in soup.find_all(style=re.compile(r"inline-block", re.I)):
        if el.parent is None or el.get_text().strip():
            continue
        m = re.search(r"(?<![-\w])width\s*:\s*([\d.]+)\s*(pt|px)", el.get("style", ""), re.I)
        if m and float(m.group(1)) * (4 / 3 if m.group(2).lower() == "pt" else 1) >= DOM_WIDE_PX:
            # 표 칸 안의 빈 상자는 칸 안 여백일 뿐이다 (칸 구분은 표가 이미 한다)
            el.replace_with(NavigableString(" " if el.find_parent(["td", "th"]) else " \x00 "))  # 칸 표시 (줄 끝이면 지움)
    for tr in soup.find_all("tr"):
        if tr.parent is None:
            continue
        cells = []
        for ch in list(tr.children):  # 보통은 <td>/<th>; 칸 밖에 놓인 글자(깨진 HTML)도 한 칸으로 살린다
            if isinstance(ch, Tag) and ch.name in ("td", "th"):
                cells.append(_cell_text(ch))
            elif isinstance(ch, Tag) and ch.find(["td", "th"]):
                cells += [_cell_text(c) for c in ch.find_all(["td", "th"])]
            elif isinstance(ch, Tag) or (type(ch) is NavigableString):
                cells.append(_cell_text(ch) if isinstance(ch, Tag) else _squash(str(ch)))
        cells = [c for c in cells if c]
        tr.replace_with(NavigableString("\n" + " | ".join(cells) + "\n"))
    for br in soup.find_all("br"):
        br.replace_with(" " if _br_inside_phrase(br) else "\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = (re.sub(r"(?: ?\x00 ?)+", " | ", _squash(line).strip("\x00 "))  # 엔티티는 BeautifulSoup가 이미 풀었다
             for line in soup.get_text("").splitlines())
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ------------------------------------------------------------------ PDF형 HTML
_NUM = r"(-?[\d.]+)px"


def _style(tag: Tag) -> str:
    return tag.get("style", "") or ""


def _px(style: str, prop: str) -> float | None:
    m = re.search(rf"(?<![-\w]){prop}\s*:\s*{_NUM}", style)
    return float(m.group(1)) if m else None


def _css_classes(soup: BeautifulSoup) -> dict[str, str]:
    """<style> 안의 '.이름{...}' 규칙 (pdf2htmlEX는 좌표·글자 크기를 클래스로 주기도 한다)."""
    rules: dict[str, str] = {}
    for st in soup.find_all("style"):
        for name, body in re.findall(r"\.([\w-]+)\s*\{([^}]*)\}", st.get_text()):
            rules.setdefault(name, body)
    return rules


def _prop(tag: Tag, prop: str, css: dict[str, str]) -> float | None:
    v = _px(_style(tag), prop)
    if v is not None:
        return v
    for c in tag.get("class", []):
        if c in css:
            v = _px(css[c], prop)
            if v is not None:
                return v
    return None


def _main_font_size(div: Tag, css: dict[str, str]) -> float:
    """줄의 글자 크기 = 그 줄 글자 대부분이 쓰는 크기 (글머리 기호·첨자처럼 일부만 다른 크기는 무시)."""
    def size_of(el: Tag) -> float | None:
        for u in [el, *el.parents]:
            if not isinstance(u, Tag):
                continue
            vals = re.findall(rf"font-size\s*:\s*{_NUM}", _style(u))
            vals = [float(v) for v in vals if float(v) > 1.0]
            if vals:
                return vals[-1]
            cls_v = None
            for c in u.get("class", []):
                if c.startswith("fs") and c in css:
                    cls_v = _px(css[c], "font-size")
            if cls_v and cls_v > 1.0:
                return cls_v
            if u is div:
                break
        return None
    weight: dict[float, int] = {}
    for sNode in div.find_all(string=True):
        if type(sNode) is NavigableString and sNode.strip():
            v = size_of(sNode.parent) or 1.0
            weight[v] = weight.get(v, 0) + len(sNode.strip())
    return max(weight, key=weight.get) if weight else 1.0


WIDE_GAP = 5.0  # 한 줄 안에서 글자 크기의 이 배수보다 넓은 빈칸 = 서로 다른 항목(머리말 좌우, 흐름도 칸)


def _line_text(div: Tag, css: dict[str, str], fs: float) -> str:
    """한 줄(div.t) 글자. 빈 간격 조각(class '_')은 폭으로 판단한다:
    글자 크기의 15% 이하 = 붙임(글자 간격 보정), 그보다 넓으면 공백, WIDE_GAP배보다 넓으면 ' | '(다른 항목)."""
    out: list[str] = []

    def walk(el: Tag) -> None:
        for node in el.children:
            if type(node) is NavigableString:  # 주석은 화면 글자가 아니다
                out.append(str(node))
            elif isinstance(node, Tag):
                if "_" in node.get("class", []) and not node.get_text().strip():
                    w = abs(_prop(node, "margin-left", css) or _prop(node, "width", css) or 0.0)
                    if w > WIDE_GAP * fs:
                        out.append(" \x00 ")  # 칸 표시 (줄 앞·뒤의 빈칸이면 아래에서 지운다)
                    elif w > 0.15 * fs:
                        out.append(" ")
                    elif node.get_text():
                        out.append(node.get_text())  # 폭이 작아도 안에 든 공백 글자는 그대로
                else:
                    walk(node)

    walk(div)
    text = _squash("".join(out)).strip("\x00 ")
    return re.sub(r"(?: ?\x00 ?)+", " | ", text)


def pdf_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "lxml")
    css = _css_classes(soup)
    pages_out = []
    for page in soup.select("div.pf"):
        rows: list[dict] = []  # 같은 높이의 조각을 모은 행
        for t in page.select("div.t"):
            fs = _main_font_size(t, css)
            x = _prop(t, "left", css) or 0.0
            y = _prop(t, "bottom", css) or 0.0
            for anc in t.parents:  # 클립 상자(div.c)의 좌표를 더해 페이지 기준 좌표로
                if anc is page:
                    break
                if isinstance(anc, Tag) and "c" in anc.get("class", []):
                    x += _prop(anc, "left", css) or 0.0
                    y += _prop(anc, "bottom", css) or 0.0
            text = _line_text(t, css, fs)
            if not text:
                continue
            est_w = 0.45 * fs * len(text)  # 글자 폭 추정 (pdf2htmlEX는 조각의 폭을 주지 않는다)
            r = rows[-1] if rows else None
            dy = (y - r["y"]) if r else 0.0
            same_row = r is not None and (
                abs(dy) < 0.35 * max(fs, r["fs"])
                or (fs < 0.85 * r["fs"] and -0.4 * r["fs"] < dy < 0.7 * r["fs"])  # 작은 글씨의 위·아래 첨자(®, ™, 각주 번호)
            )
            if same_row:
                gap = x - r["x_end"]
                if fs < 0.85 * r["fs"] and len(text) <= 4:
                    sep = ""  # 첨자는 앞 글자에 붙인다
                elif gap > 1.5 * r["fs"] and not (re.match(r"[a-z]", text) or re.search(CONT_END, r["parts"][-1].rstrip())):
                    sep = " | "  # 멀리 떨어진 같은 높이의 조각 = 표의 다른 칸
                else:
                    sep = " "
                r["parts"].append(sep + text)
                r["x_end"] = max(r["x_end"], x + est_w)
            else:
                rows.append({"x": x, "y": y, "fs": fs, "x_end": x + est_w, "parts": [text]})
        if not rows:
            continue
        # 보통 줄 간격은 글자 크기마다 다르다 (큰 제목은 줄 간격도 크다)
        by_fs: dict[float, list[float]] = {}
        for i in range(1, len(rows)):
            d = rows[i - 1]["y"] - rows[i]["y"]
            if abs(rows[i - 1]["fs"] - rows[i]["fs"]) < 0.01 and 0 < d < 3 * rows[i]["fs"]:
                by_fs.setdefault(round(rows[i]["fs"], 1), []).append(d)
        pitch_of = {k: median(v) for k, v in by_fs.items()}
        paras: list[str] = []
        cur = ""
        prev = None
        for r in rows:
            line = "".join(r["parts"]).strip()
            # 이어지는 줄이라는 글자 증거: 앞 줄이 CONT_END로 끝나거나, 다음 줄이 소문자·숫자로 시작
            cont = bool(prev) and (bool(re.search(CONT_END, cur)) or bool(re.match(r"[a-z0-9$%]", line)))
            limit = 1.35 * pitch_of.get(round(r["fs"], 1), 1.25 * r["fs"])
            if cont:
                limit = max(limit, 2.0 * r["fs"])
            new_para = (
                prev is None
                or not (0 < prev["y"] - r["y"] <= limit)  # 줄 간격이 크거나 위로 돌아감(단 바뀜)
                or abs(prev["fs"] - r["fs"]) > 0.15 * r["fs"]    # 글자 크기가 바뀜(제목 등)
                or line[:1] in BULLETS                             # 글머리 기호로 시작
                or " | " in line or " | " in cur                   # 표의 행은 한 줄씩
            )
            if new_para and cur:
                paras.append(cur)
                cur = line
            else:
                if cur.endswith("-") and line[:1].islower():
                    cur += line  # 줄 끝 하이픈: 하이픈은 남기고 붙인다
                else:
                    cur = f"{cur} {line}" if cur else line
            prev = r
        if cur:
            paras.append(cur)
        pages_out.append("\n\n".join(_squash(p) for p in paras))
    # SEC 제출 머리(<TYPE>·<SEQUENCE>·<FILENAME>·<DESCRIPTION>)는 페이지 밖에 있으므로 따로 앞에 붙인다
    head = [m.strip() for m in re.findall(r"<(?:TYPE|SEQUENCE|FILENAME|DESCRIPTION)>([^<\r\n]*)", raw[:3000])]
    return ("\n".join(h for h in head if h) + "\n\n" + "\n\n".join(pages_out)).strip()


_SPLIT_DATE = [
    re.compile(rf"\b({MONTHS} \d{{1,2}},)[ \t]*\n\s*(\d{{4}}\b)"),   # 'June 29,⏎2028'
    re.compile(rf"\b({MONTHS})[ \t]*\n\s*(\d{{1,2}}, ?\d{{4}}\b)"),  # 'June⏎29, 2028'
]


def _join_split_dates(text: str) -> str:
    """날짜는 하나의 값이다: 날짜 가운데의 줄바꿈은 공백으로 바꾼다 (글자는 그대로)."""
    for pat in _SPLIT_DATE:
        text = pat.sub(r"\1 \2", text)
    return text


def _space_after_bullets(text: str) -> str:
    """글머리 기호(●•▪◦■)는 화면에서 기호 칸의 폭만큼 떨어져 있다: 바로 붙은 글자 앞에 공백을 넣는다 (글자는 그대로)."""
    return re.sub(r"([●•▪◦■])(?=[^\s|●•▪◦■])", r"\1 ", text)


def convert(raw: bytes | str) -> str:
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = pdf_to_text(s) if is_pdf_layout(s) else dom_to_text(s)
    return _join_split_dates(_space_after_bullets(text))
