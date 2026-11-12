"""차트 한글 표시 설정."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib import font_manager

KOREAN_FONTS = ["AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]


def setup_korean_font() -> str | None:
    """설치된 한글 폰트를 찾아 matplotlib 기본 폰트로 지정한다 (macOS·Windows·Linux)."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in KOREAN_FONTS:
        if name in installed:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
    return None
