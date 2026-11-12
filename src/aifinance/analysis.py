"""모듈 6: 상품군 분석용 도우미."""

from __future__ import annotations

import re

import duckdb
import pandas as pd

from .config import DATA_DIR

FULL_DB = DATA_DIR / "aifinance_full.duckdb"

# 차감(deduction)·변동성 제어가 내장된 규칙 기반 지수. 대부분 JPM 이 개발에 관여하거나 JPM 브랜드를 단다.
STRATEGY_INDEX = re.compile(r"MQ|MerQube|J\.P\. Morgan|Risk Control|Vol Advantage|Dynamic|Daily Deduction|Excess Return Index", re.I)
BROAD_INDEX = {"SPX", "RTY", "NDX", "INDU", "SX5E", "NDXT", "MXEA", "TPX", "UKX"}

FAMILY_KO = {
    "autocall_contingent_coupon": "오토콜·조건부쿠폰",
    "autocall_call_premium": "오토콜·상환프리미엄",
    "issuer_call_contingent_coupon": "발행사콜·조건부쿠폰",
    "leveraged_buffer": "레버리지·버퍼",
    "leveraged_barrier": "레버리지·배리어",
    "dual_directional": "듀얼디렉셔널",
    "digital": "디지털",
    "principal_protected": "원금보장",
    "other": "미분류",
}


def underlying_group(names: str | None, kinds: str | None) -> str:
    """기초자산 묶음을 분석용 그룹으로: 전략지수 / 광역지수 / 개별주식 / ETF / 혼합 / 금리·기타."""
    if not isinstance(names, str) or not names:
        return "금리·기타"
    parts = [n.strip() for n in names.split(" / ")]
    if any(STRATEGY_INDEX.search(p) and p not in ("SPXFP",) for p in parts):
        return "전략지수"
    kinds_set = set((kinds or "").split(","))
    if kinds_set == {"stock"}:
        return "개별주식"
    if kinds_set == {"etf"}:
        return "ETF"
    if kinds_set == {"index"}:
        return "광역지수"
    return "혼합"


def load_products(db_path=FULL_DB) -> pd.DataFrame:
    """products 뷰 + 분석용 파생 컬럼."""
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute("SELECT * FROM products").df()
    con.close()
    df["family_ko"] = df.product_family.map(FAMILY_KO)
    df["und_group"] = [underlying_group(n, k) for n, k in zip(df.underlying_names, df.underlying_kinds)]
    df["margin"] = 1000 - df.estimated_value_per_1000                    # 발행가 − 추정가치 ($1,000 당)
    df["margin_pa"] = df.margin / df.tenor_years.where(df.tenor_years > 0)  # 연 환산
    df["pricing_week"] = pd.to_datetime(df.pricing_date).dt.to_period("W").dt.start_time
    return df
