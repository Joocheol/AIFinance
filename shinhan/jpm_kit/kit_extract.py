"""상품 조건(텀시트) 규칙 추출기와 채점기 — 실습 키트용.

- TermSheet: 추출할 필드의 정의 (비율은 소수: 70% → 0.70)
- extract(text, accession): 정규식 규칙으로 공시 원문에서 조건을 뽑는다  ← 활동 4에서 이 규칙을 고칩니다
- load_gold / compare / field_accuracy: 정답 27건과 필드별 채점

원본: AIFinance 저장소 src/aifinance/{schema,extract,evaluate}.py
"""

from __future__ import annotations

import json
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

# ================================================================ 스키마
ProductFamily = Literal[
    "autocall_contingent_coupon",  # 자동조기상환 + 조건부 쿠폰 (Auto Callable Contingent Interest 등)
    "issuer_call_contingent_coupon",  # 발행사 콜 + 조건부 쿠폰 (Callable Contingent Interest)
    "autocall_call_premium",  # 자동조기상환 + 상환 프리미엄, 쿠폰 없음 (Review Notes, Auto Callable Accelerated Barrier 등)
    "leveraged_buffer",  # 상승 참여 + 버퍼 (Buffered Return Enhanced, Buffered Equity)
    "leveraged_barrier",  # 상승 참여 + 배리어 (Accelerated Barrier, Trigger PLUS, Market Linked Securities—Leveraged Upside)
    "dual_directional",  # 하락 시 절대수익 (Dual Directional)
    "digital",  # 디지털 수익 (Digital)
    "principal_protected",  # 원금보장
    "other",
]

FIELD_GROUPS = {
    "기본": ["product_name", "product_family", "principal_amount_usd", "cusip"],
    "일정": ["pricing_date", "issue_date", "maturity_date"],
    "기초자산": ["underlyings", "basket_type"],
    "쿠폰": ["coupon_rate_pa", "coupon_frequency", "coupon_barrier_pct", "memory_coupon"],
    "조기상환": ["autocall", "autocall_frequency", "autocall_trigger_pct", "issuer_callable"],
    "하방": ["downside_type", "barrier_pct", "buffer_pct"],
    "상방": ["upside_participation", "cap_pct", "digital_return_pct"],
    "가치": ["estimated_value_per_1000"],
}


class Underlying(BaseModel):
    name: str = Field(description="기초자산 이름. 예: 'S&P 500 Index', 'NVIDIA Corporation common stock'")
    ticker: str | None = Field(None, description="Bloomberg 티커가 원문에 있으면 그대로. 예: 'SPX', 'NVDA'")
    kind: Literal["index", "stock", "etf", "other"]
    weight: float | None = Field(None, description="가중 바스켓일 때 비중(소수). 그 외 null")


class TermSheet(BaseModel):
    accession_number: str
    product_name: str = Field(description="표지의 상품명 전체")
    product_family: ProductFamily
    principal_amount_usd: float | None = Field(None, description="총 발행금액(USD)")
    cusip: str | None = None

    pricing_date: date | None = None
    issue_date: date | None = Field(None, description="Original Issue Date / Settlement Date")
    maturity_date: date | None = None

    underlyings: list[Underlying] = Field(default_factory=list)
    basket_type: Literal["single", "worst_of", "weighted_basket"] | None = None

    coupon_rate_pa: float | None = Field(None, description="연 환산 조건부/고정 쿠폰율")
    coupon_frequency: Literal["monthly", "quarterly", "semiannual", "annual"] | None = None
    coupon_barrier_pct: float | None = Field(None, description="쿠폰 지급 배리어(최초가 대비)")
    memory_coupon: bool | None = Field(None, description="미지급 쿠폰 누적(메모리) 여부")

    autocall: bool = Field(False, description="기초자산 수준에 따른 자동조기상환 여부")
    autocall_frequency: Literal["monthly", "quarterly", "semiannual", "annual"] | None = None
    autocall_trigger_pct: float | None = Field(None, description="첫 자동조기상환 기준(최초가 대비). 계단식이면 첫 값")
    issuer_callable: bool = Field(False, description="발행사 재량 조기상환 여부")

    downside_type: Literal["barrier", "buffer", "principal_protected", "none"] | None = Field(
        None, description="barrier: 만기 배리어 하회 시 1:1 손실, buffer: 버퍼 초과분만 손실"
    )
    barrier_pct: float | None = Field(None, description="만기 원금 손실 배리어(Trigger Value 등, 최초가 대비)")
    buffer_pct: float | None = Field(None, description="버퍼 크기. 예: 15% 버퍼 → 0.15")

    upside_participation: float | None = Field(None, description="상승 참여율(Upside Leverage Factor). 예: 2.0")
    cap_pct: float | None = Field(None, description="최대 수익률(Maximum Return). 예: 0.305")
    digital_return_pct: float | None = None

    estimated_value_per_1000: float | None = Field(None, description="JPM 추정가치($1,000 당)")


def tenor_years(ts: TermSheet) -> float | None:
    if ts.issue_date and ts.maturity_date:
        return round((ts.maturity_date - ts.issue_date).days / 365.25, 2)
    return None


# ================================================================ 추출 규칙


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
    """표지의 상품명. 판매사 플랫폼별 형식을 모두 다룬다.

    JPM : 'Structured Investments $775,000 Auto Callable … Notes Linked to … due November 12, 2032'
    WF  : '$1,746,000 Market Linked Securities — Auto-Callable … Linked to … due August 22, 2028'
    UBS : 'Trigger GEARS $5,667,750 Linked to the EURO STOXX 50® Index due September 30, 2036'
    GS  : 'Medium-Term Notes, Series A $72,680,000 Digital Equity Notes due 2029 (Linked to a Basket)'
    """
    head = re.sub(r"\s+", " ", text[:6000])
    m = re.search(rf"((?:Notes|Securities|PLUS|GEARS)\b.{{0,400}}?\bdue\s+(?:{DATE}|\d{{4}})(?:\s*\((?:Linked|Based) [^)]{{0,200}}\))?)", head)
    if not m:
        return None
    # 상품명 시작점: 'due' 앞의 문장에서 머리 부분(발행사명·프로그램명)을 잘라내고 금액은 지운다
    start = head.rfind("Structured Investments", 0, m.start())
    window = head[max(start, m.start() - 250) : m.end()]
    window = re.sub(r"\$\s?[\d,]{5,}(?:\.\d+)?\s*", "", window)
    for cut in [r"Structured Investments", r"Series A", r"LLC", r"Pricing Supplement", r"Dated \w+ \d{1,2}, \d{4}"]:
        window = re.split(cut, window)[-1]
    return window.strip(" |—–-") or None


FAMILY_RULES = [
    ("dual_directional", r"Dual Directional"),
    ("principal_protected", r"Principal Protect|Principal Protection|Fixed Rate Notes|Range Accrual|Fixed Coupon Notes"),
    ("autocall_call_premium", r"Review Notes|Auto Callable (?:Accelerated|Buffered|Barrier)|Autocallable Leveraged|Auto-Callable (?:Leveraged|Securities with Fixed)"),
    ("issuer_call_contingent_coupon", r"(?<!Auto )(?<!Auto-)Callable Contingent"),
    ("autocall_contingent_coupon", r"Auto[- ]?Callable|Contingent Income|Contingent Coupon"),
    ("digital", r"Digital|Trigger Step|Step Securities"),
    ("leveraged_barrier", r"Contingent Buffered"),  # 조건부 버퍼 = 사실상 배리어 (모듈 5 답변 평가에서 발견)
    ("leveraged_buffer", r"Buffered"),
    ("leveraged_barrier", r"Accelerated Barrier|Trigger PLUS|Leveraged Upside|Return Enhanced|PLUS|GEARS"),
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
    # Wells Fargo 형식은 'Lowest Performing' 이라고 쓴다 (모듈 5 답변 평가에서 발견)
    if re.search(r"(?:Least|Lesser|Lowest|Worst) Performing", (title or "") + head[:3000], re.I):
        basket = "worst_of"
    elif title and re.search(r"Basket", title, re.I):
        basket = "weighted_basket"
    else:
        basket = "single"
    names: list[str] = []
    if title:
        m = (re.search(r"(?:Linked to|Based on)\s+(?:the\s+)?(.+?)\s+due\s", title)
             or re.search(r"\((?:Linked to|Based on)\s+(?:the\s+)?(.+?)\)", title))  # GS 형식: '… due 2029 (Linked to …)'
        if m:
            body = re.sub(r"^(?:Least|Lesser|Lowest|Worst) Perform\w* of\s+(?:the\s+)?", "", m.group(1), flags=re.I)
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
    # 조건부 버퍼: 하락이 버퍼 이내면 원금 보전, 넘으면 하락분 전체 손실 → 경제적으로 (1 - 버퍼) 배리어와 같다
    if buffer is not None and re.search(r"Contingent Buffer", flat):
        barrier, buffer = round(1 - buffer, 6), None
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
        cusip=_first(flat, [
            r"CUSIP(?:\s*/\s*ISIN| no\.| No\.| number)?\s*:?\s*\|?\s*([0-9A-Z]{9})\b",
            # UBS 형식은 CUSIP 을 표의 다른 행에 둔다 → JPM 발행사 CUSIP 접두어로 문서에서 찾는다
            r"\b((?:4666[01]|4813[0-9])[0-9A-Z]{4})\b",
        ]),
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
    """JPM 추정가치를 액면 $1,000 기준으로.

    액면은 문구('$10.00 per security')로 찾으면 수수료 문구와 헷갈린다(모듈 6에서 발견).
    추정가치는 항상 액면의 80~110% 근처이므로 값 자체로 액면($10/$25/$100/$1,000)을 정한다.
    """
    m = re.search(r"estimated value of the (?:notes|securities)[^$]{0,200}?\$\s?([\d,]+\.\d+)", text, re.I | re.S)
    if not m:
        return None
    value = _num(m.group(1))
    for denomination in (1000.0, 100.0, 25.0, 10.0):
        if 0.8 <= value / denomination <= 1.1:
            return round(value * 1000 / denomination, 4)
    return None  # 어느 액면과도 맞지 않으면 추출 오류로 보고 비운다


# ================================================================ 채점



EVAL_FIELDS = [f for fields in FIELD_GROUPS.values() for f in fields if f != "product_name"]


def load_gold(gold_dir: Path) -> dict[str, TermSheet]:
    out = {}
    for p in sorted(Path(gold_dir).glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d.pop("_evidence", None)
        out[d["accession_number"]] = TermSheet.model_validate(d)
    return out


def _same(field: str, a, b) -> bool:
    if field == "underlyings":  # 개수와 유형 구성만 비교 (이름 표기는 문서마다 달라서)
        return sorted(u.kind for u in a) == sorted(u.kind for u in b)
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().upper() == b.strip().upper()
    return a == b


def compare(preds: dict[str, TermSheet], gold: dict[str, TermSheet]) -> pd.DataFrame:
    """행 = (문서, 필드). 'outcome' 은 correct / wrong / missed(놓침) / spurious(헛추출)."""
    rows = []
    for acc, g in gold.items():
        p = preds.get(acc)
        for f in EVAL_FIELDS:
            gv, pv = getattr(g, f), getattr(p, f) if p else None
            empty_g = gv in (None, [])
            empty_p = pv in (None, [])
            if empty_g and empty_p:
                outcome = "correct"
            elif empty_p:
                outcome = "missed"
            elif empty_g:
                outcome = "spurious"
            else:
                outcome = "correct" if _same(f, pv, gv) else "wrong"
            rows.append({"accession_number": acc, "field": f, "gold": gv, "pred": pv, "outcome": outcome})
    return pd.DataFrame(rows)


def field_accuracy(cmp: pd.DataFrame) -> pd.DataFrame:
    tbl = pd.crosstab(cmp.field, cmp.outcome)
    for c in ["correct", "wrong", "missed", "spurious"]:
        if c not in tbl:
            tbl[c] = 0
    tbl = tbl[["correct", "wrong", "missed", "spurious"]]
    tbl["accuracy"] = (tbl.correct / tbl.sum(axis=1)).round(3)
    return tbl.loc[[f for f in EVAL_FIELDS if f in tbl.index]]
