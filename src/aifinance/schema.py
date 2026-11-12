"""구조화 노트 텀시트 스키마 (모듈 2 데이터 사전).

비율은 모두 소수로 적는다: 70% → 0.70, 연 9.25% → 0.0925.
원문에 없거나 해당되지 않는 항목은 null.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

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
