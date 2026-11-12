"""경로·상수·환경변수 설정."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # 원문 공시(HTML)
INTERIM_DIR = DATA_DIR / "interim"  # 목록·메타데이터(parquet)

# JP Morgan 구조화 노트 발행 법인과 보증인
JPM_FINANCIAL_CIK = 1665650  # JPMorgan Chase Financial Company LLC (발행사)
JPM_PARENT_CIK = 19617  # JPMorgan Chase & Co. (보증인)

load_dotenv(PROJECT_ROOT / ".env")


def sec_user_agent() -> str:
    """.env 의 SEC_USER_AGENT 를 읽는다. 없으면 설정 방법을 알려 준다."""
    ua = os.getenv("SEC_USER_AGENT", "").strip()
    if not ua or "your.email" in ua:
        raise RuntimeError(
            "SEC_USER_AGENT 가 설정되지 않았습니다. "
            ".env.example 을 .env 로 복사하고 '이름 이메일' 형식으로 채우세요."
        )
    return ua
