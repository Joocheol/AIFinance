"""규칙 기반 텀시트 추출기 (모듈 2 기준선).

Claude가 만든 정답셋(gold/)으로 채점하며 개선해 나가는 것이 모듈 2의 핵심이다.
API 없이 2만 건 전량에 돌릴 수 있도록 정규식만 사용한다.
"""

from __future__ import annotations

import re
import statistics
from datetime import date, datetime

from .schema import TermSheet, Underlying

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE = rf"{MONTH}\s+\d{{1,2}},\s+\d{{4}}"
PCT = r"(\d{1,3}(?:\.\d+)?)\s?%"
SEP = r"\s?[*†‡]?\s?(?:\d\s?)?:?\s*\|?\s*"  # 'Label*: ' / 'Label | ' / 각주 'Label 1 : |' 'Label † :' 등 구분자
MIN = r"(?:[Aa]t least |[Aa]t most |[Aa]pproximately )?"  # 예비본의 미확정 표기: "At least 8.00%"


# ---------------------------------------------------------------- 변환 도우미
def _date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def _first(text: str, patterns: list[str], flags=re.I) -> str | None:
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(1)
    return None


def _pct(text: str, patterns: list[str]) -> float | None:
    """첫 번째로 맞는 패턴의 % 값을 소수로."""
    v = _first(text, patterns)
    return round(float(v) / 100, 6) if v else None


def _num(s: str | None) -> float | None:
    return float(s.replace(",", "")) if s else None


def _frequency(dates: list[date]) -> str | None:
    """관찰일 목록의 간격(중앙값)으로 빈도를 추정."""
    if len(dates) < 2:
        return None
    gap = statistics.median((b - a).days for a, b in zip(dates, dates[1:]))
    for name, days in [("monthly", 30), ("quarterly", 91), ("semiannual", 182), ("annual", 365)]:
        if abs(gap - days) <= days * 0.25:
            return name
    return None


def _date_list(text: str, label: str) -> list[date]:
    """'<label>*: 날짜, 날짜, … and 날짜' 형태의 일정 목록을 읽는다."""
    # 'As specified under …' 처럼 다른 곳을 가리키는 경우를 건너뛰고, 바로 날짜가 이어지는 위치를 쓴다
    m = next((m for m in re.finditer(label + SEP, text) if re.match(r"\s*(?:\(.{0,40}\)\s*)?:?\s*" + DATE, text[m.end():m.end() + 80])), None)
    if not m:
        return []
    out = []
    for dm in re.finditer(DATE, text[m.end() : m.end() + 6000]):
        if out and dm.start() - prev_end > 25:  # 목록이 끝남
            break
        out.append(_date(dm.group(0)))
        prev_end = dm.end()
    return out


# ---------------------------------------------------------------- 상품명·분류
def extract_title(text: str) -> str | None:
    head = re.sub(r"\s+", " ", text[:6000])
    m = re.search(rf"((?:Notes|Securities|PLUS)\b.{{0,400}}?\bdue\s+{DATE})", head)
    if not m:
        return None
    # 상품명 시작점: 'due' 앞의 문장에서 머리 부분(발행사명·금액·프로그램명)을 잘라낸다
    start = head.rfind("Structured Investments", 0, m.start())
    window = head[max(start, m.start() - 250) : m.end()]
    for cut in [r"Structured Investments", r"\$\s?[\d,]{5,}", r"Series A", r"LLC", r"Pricing Supplement"]:
        parts = re.split(cut, window)
        window = parts[-1]
    return window.strip(" |—–-")


FAMILY_RULES = [
    ("dual_directional", r"Dual Directional"),
    ("principal_protected", r"Principal Protect|Principal Protection"),
    ("autocall_call_premium", r"Review Notes|Auto Callable (?:Accelerated|Buffered|Barrier)|Autocallable Leveraged|Auto-Callable (?:Leveraged|Securities with Fixed)"),
    ("issuer_call_contingent_coupon", r"(?<!Auto )(?<!Auto-)Callable Contingent"),
    ("autocall_contingent_coupon", r"Auto[- ]?Callable|Contingent Income|Contingent Coupon"),
    ("digital", r"Digital"),
    ("leveraged_buffer", r"Buffered"),
    ("leveraged_barrier", r"Accelerated Barrier|Trigger PLUS|Leveraged Upside|Return Enhanced|PLUS"),
]


def classify(title: str | None) -> str:
    for family, pattern in FAMILY_RULES:
        if title and re.search(pattern, title, re.I):
            return family
    return "other"


# 자주 나오는 기초자산의 표준 이름 → 티커. (모듈 6 집계용. 실습으로 확장)
UNDERLYING_ALIASES = {
    "S&P 500 Index": "SPX",
    "Russell 2000 Index": "RTY",
    "Nasdaq-100 Index": "NDX",
    "Dow Jones Industrial Average": "INDU",
    "EURO STOXX 50 Index": "SX5E",
    "Nasdaq-100 Technology Sector Index": "NDXT",
    "S&P 500 Futures Excess Return Index": "SPXFP",
    "MerQube US Large-Cap Vol Advantage Index": "MQUSLVA",
    "MerQube US Tech+ Vol Advantage Index": "MQUSTVA",
    "MerQube US Gold Vol Advantage Index": "MQUSGVA",
    "MSCI EAFE Index": "MXEA",
    "iShares MSCI EAFE ETF": "EFA",
    "TOPIX Index": "TPX",
    "FTSE 100 Index": "UKX",
}
CORP_SUFFIX = r",\s*(Inc\.|Ltd\.|N\.V\.|S\.A\.|plc|L\.P\.|Co\.|Corp\.|LLC)"


def normalize_underlying(name: str) -> str:
    """'the S&P 500 ® Index' → 'S&P 500 Index'. 상표 기호·SM 표기·관사 제거."""
    n = re.sub(r"[®™℠]|(?<=\w)SM\b", "", name)
    n = re.sub(r"^(?:the|The)\s+", "", n)
    n = re.sub(r"-\s+", "-", n)  # 'Nasdaq- 100' → 'Nasdaq-100'
    return re.sub(r"\s+", " ", n).strip(" ,")


def extract_underlyings(title: str | None, text: str) -> tuple[list[Underlying], str | None]:
    head = text[:8000]
    if re.search(r"Least Performing|Lesser Performing|Worst Performing", (title or "") + head[:3000], re.I):
        basket = "worst_of"
    elif title and re.search(r"Basket", title, re.I):
        basket = "weighted_basket"
    else:
        basket = "single"
    names: list[str] = []
    if title:
        m = re.search(r"(?:Linked to|Based on)\s+(?:the\s+)?(.+?)\s+due\s", title)
        if m:
            body = re.sub(r"^(?:Least|Lesser|Worst) Perform\w* of\s+(?:the\s+)?", "", m.group(1), flags=re.I)
            body = re.sub(CORP_SUFFIX, r" \1", body)  # 'Affirm Holdings, Inc.' 가 쉼표에서 쪼개지지 않게
            names = [normalize_underlying(n) for n in re.split(r",\s*(?:and\s+)?(?:the\s+)?|\s+and\s+(?:the\s+)?", body)]
            names = [n for n in names if n]
    unds = []
    for n in names:
        kind = (
            "etf" if re.search(r"ETF|Fund|Trust", n) else
            "index" if re.search(r"Index|Average|Rate\b", n) else
            "stock" if re.search(r"Stock|Shares|Inc\.|Corporation|Depositary|Company|plc|Ltd\.", n, re.I) else
            "other"
        )
        unds.append(Underlying(name=n, ticker=UNDERLYING_ALIASES.get(n), kind=kind))
    return unds, basket


# ---------------------------------------------------------------- 메인
def extract(text: str, accession_number: str) -> TermSheet:
    t = text[:60000]
    flat = re.sub(r"\s+", " ", t)
    title = extract_title(t)
    family = classify(title)
    unds, basket = extract_underlyings(title, t)

    coupon_rate = _pct(flat, [
        rf"Contingent Interest Rate{SEP}{MIN}{PCT} per annum",
        rf"contingent coupon rate ?”? (?:is|will be) {MIN}{PCT} per annum",
        rf"Contingent Coupon Rate{SEP}{MIN}{PCT} per annum",
        rf"Interest Rate{SEP}{MIN}{PCT} per annum",
    ])
    review_dates = _date_list(flat, r"(?:Interest Review Dates|Review Dates|Observation Dates|Calculation days|Coupon Determination Dates)")
    autocall_dates = _date_list(flat, r"(?:Autocall Review Dates|Call Determination Dates|Review Dates)")
    is_autocall = bool(re.search(r"automatically called|Automatic Call|Auto[- ]?Callable|Autocall", flat[:20000], re.I))
    buffer = _pct(flat, [rf"Buffer Amount{SEP}{PCT}", rf"buffer amount ?”? is {PCT}"])
    barrier = _pct(flat, [
        rf"Trigger Value{SEP}(?:With respect to each \w+, )?{PCT}",
        rf"Barrier Amount{SEP}(?:With respect to each \w+, )?{PCT}",
        rf"Trigger [Ll]evel{SEP}.{{0,80}}?{PCT}",
        rf"[Dd]ownside threshold level{SEP}.{{0,120}}?equal to {PCT}",
        rf"Threshold Value{SEP}(?:With respect to each \w+, )?{PCT}",
    ])
    if re.search(r"Principal Protect", title or "", re.I):
        downside = "principal_protected"
    elif buffer is not None:
        downside = "buffer"
    elif barrier is not None:
        downside = "barrier"
    else:
        downside = None

    leverage = _first(flat, [rf"Upside Leverage Factor{SEP}{MIN}(\d+(?:\.\d+)?)", r"leverage factor ?”? is (\d+(?:\.\d+)?)"])
    participation = _pct(flat, [rf"(?:Upside )?Participation Rate{SEP}{MIN}{PCT}", rf"upside participation rate ?”? is {PCT}"])

    return TermSheet(
        accession_number=accession_number,
        product_name=title or "",
        product_family=family,
        principal_amount_usd=_num(_first(flat, [
            r"Aggregate principal amount\s*:?\s*\|?\s*\$\s?([\d,]+)",
            r"Structured Investments\s*\|?\s*\$\s?([\d,]{5,})",
            r"^.{0,1500}?\$\s?([\d,]{6,})(?:\s|$)",
        ], flags=re.I | re.S)),
        cusip=_first(flat, [r"CUSIP(?:/ISIN| no\.| No\.| number)?\s*:?\s*\|?\s*([0-9A-Z]{9})\b"]),
        pricing_date=_date(_first(flat, [rf"(?:Pricing|Trade|Strike) [Dd]ate{SEP}({DATE})"])),
        issue_date=_date(_first(flat, [
            rf"Original Issue Date(?: \(Settlement Date\))?{SEP}(?:On or about )?({DATE})",
            rf"(?:Original issue|Issue) [Dd]ate{SEP}(?:On or about )?({DATE})",
        ])),
        maturity_date=_date(_first(flat, [rf"(?:Stated )?[Mm]aturity [Dd]ate{SEP}({DATE})"])),
        underlyings=unds,
        basket_type=basket,
        coupon_rate_pa=coupon_rate,
        coupon_frequency=_frequency(review_dates) if coupon_rate else None,
        coupon_barrier_pct=_pct(flat, [
            rf"Interest Barrier(?:/Buffer Threshold)?{SEP}(?:With respect to each \w+, )?{PCT}",
            rf"Coupon [Bb]arrier(?: [Ll]evel| [Vv]alue)?{SEP}.{{0,120}}?{PCT}",
        ]) if coupon_rate else None,
        memory_coupon=bool(re.search(r"previously unpaid|unpaid Contingent|Memory", flat, re.I)) if coupon_rate else None,
        autocall=is_autocall,
        autocall_frequency=_frequency(autocall_dates) if is_autocall else None,
        autocall_trigger_pct=(
            _pct(flat, [rf"Call Value{SEP}(?:With respect to each \w+, )?{PCT}", rf"call threshold (?:level|value)?{SEP}.{{0,80}}?{PCT}"])
            or (1.0 if is_autocall and re.search(r"automatically called if the closing (?:level|price|value)[^.]{0,120}greater than or equal to (?:its|the) Initial Value", flat) else None)
        ) if is_autocall else None,
        issuer_callable=bool(re.search(r"we may redeem|may, in our sole discretion|redeem the notes early|callable at our option", flat, re.I)),
        downside_type=downside,
        barrier_pct=barrier,
        buffer_pct=buffer,
        upside_participation=float(leverage) if leverage else participation,
        cap_pct=_pct(flat, [rf"Maximum (?:Upside )?Return{SEP}{MIN}{PCT}", rf"maximum return ?”? is {PCT}"]),
        digital_return_pct=_pct(flat, [rf"Digital Return{SEP}{MIN}{PCT}"]),
        estimated_value_per_1000=estimated_value(text),
    )


def estimated_value(text: str) -> float | None:
    """JPM 추정가치를 액면 $1,000 기준으로. UBS 형식처럼 액면이 $10 이면 100배로 환산."""
    m = re.search(r"estimated value of the (?:notes|securities)[^$]{0,200}?\$\s?([\d,]+\.\d+)(?:\s+per\s+\$\s?([\d,]+))?",
                  text, re.I | re.S)
    if not m:
        return None
    value = _num(m.group(1))
    if m.group(2):  # "... $9.901 per $10"
        denomination = _num(m.group(2))
    else:  # "... per unit" → "$10 principal amount per unit" 같은 액면 표기를 찾는다
        d = re.search(r"\$\s?(10|25|100|1,000) (?:stated )?principal amount per (?:unit|security|note)", text, re.I)
        denomination = _num(d.group(1)) if d else 1000.0
    return round(value * 1000 / denomination, 4)
