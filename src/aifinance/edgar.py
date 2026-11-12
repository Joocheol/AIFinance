"""SEC EDGAR 수집 클라이언트.

SEC 공정 접근 규칙(https://www.sec.gov/os/accessing-edgar-data):
- 모든 요청에 연락처가 담긴 User-Agent 를 보낸다.
- 초당 10건을 넘기지 않는다. (여기서는 여유 있게 기본 8건)
"""

from __future__ import annotations

import html
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import RAW_DIR, sec_user_agent

SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

FILING_COLUMNS = [
    "accessionNumber",
    "filingDate",
    "form",
    "primaryDocument",
    "primaryDocDescription",
    "size",
]


class EdgarClient:
    def __init__(self, user_agent: str | None = None, max_per_second: float = 8.0):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent or sec_user_agent(), "Accept-Encoding": "gzip, deflate"}
        )
        self._min_interval = 1.0 / max_per_second
        self._last_request = 0.0

    # ------------------------------------------------------------------ 기본 요청
    def get(self, url: str, params: dict | None = None, retries: int = 4) -> requests.Response:
        """속도 제한과 재시도(429/5xx)를 적용한 GET."""
        for attempt in range(retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            resp.raise_for_status()
        raise RuntimeError(f"요청 실패: {url}")

    # ------------------------------------------------------------------ 공시 목록
    def list_filings(self, cik: int, include_older: bool = False) -> pd.DataFrame:
        """회사의 공시 목록을 DataFrame 으로 반환.

        submissions API 의 'recent' 블록은 최근 약 1년(또는 최근 1,000건 이상)만 담는다.
        include_older=True 이면 과거 페이지 파일까지 모두 내려받는다(수십 번 요청).
        """
        data = self.get(SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json")).json()
        frames = [pd.DataFrame(data["filings"]["recent"])[FILING_COLUMNS]]
        if include_older:
            for f in data["filings"]["files"]:
                page = self.get(SUBMISSIONS_URL.format(name=f["name"])).json()
                frames.append(pd.DataFrame(page)[FILING_COLUMNS])
        df = pd.concat(frames, ignore_index=True)
        df["cik"] = cik
        df["filingDate"] = pd.to_datetime(df["filingDate"])
        df["url"] = [
            ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc)
            for acc, doc in zip(df["accessionNumber"], df["primaryDocument"])
        ]
        return df.sort_values("filingDate", ascending=False, ignore_index=True)

    # ------------------------------------------------------------------ 전문 검색
    def full_text_search(
        self,
        query: str,
        forms: str = "424B2",
        start: str | None = None,
        end: str | None = None,
        cik: int | None = None,
        offset: int = 0,
    ) -> tuple[int, pd.DataFrame]:
        """EDGAR 전문 검색(EFTS). 한 번에 최대 100건, offset 으로 페이지를 넘긴다.

        예) full_text_search('"Auto Callable"', start="2026-10-01", end="2026-10-31")
        """
        params = {"q": query, "forms": forms, "from": offset}
        if start or end:
            params.update({"dateRange": "custom", "startdt": start, "enddt": end})
        if cik:
            params["ciks"] = f"{cik:010d}"
        hits = self.get(FULL_TEXT_SEARCH_URL, params=params).json()["hits"]
        rows = []
        for h in hits["hits"]:
            src = h["_source"]
            acc, doc = h["_id"].split(":", 1)
            rows.append(
                {
                    "accessionNumber": acc,
                    "filingDate": src["file_date"],
                    "form": src["form"],
                    "primaryDocument": doc,
                    "url": ARCHIVE_URL.format(
                        cik=int(src["ciks"][-1]), acc=acc.replace("-", ""), doc=doc
                    ),
                }
            )
        return hits["total"]["value"], pd.DataFrame(rows)

    # ------------------------------------------------------------------ 다운로드
    def download(self, url: str, dest_dir: Path = RAW_DIR, overwrite: bool = False) -> Path:
        """공시 문서를 data/raw/<접수번호>_<파일명> 으로 저장. 이미 있으면 건너뛴다."""
        parts = url.rstrip("/").split("/")
        path = Path(dest_dir) / f"{parts[-2]}_{parts[-1]}"
        if path.exists() and not overwrite:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.get(url).content)
        return path


def html_to_text(raw: str | bytes) -> str:
    """공시 HTML 을 읽기 쉬운 평문으로 변환. 표는 셀을 ' | ' 로 이어 한 줄로 만든다."""
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # 표: 행 단위로 셀을 ' | ' 로 잇는다 (셀 안의 줄바꿈은 공백으로)
    for tr in soup.find_all("tr"):
        cells = [_squash(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        tr.replace_with(soup.new_string("\n" + " | ".join(cells) + "\n"))
    # 블록 요소 경계에만 줄바꿈을 넣는다 (인라인 <span>/<font> 는 이어 붙임)
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = (_squash(line) for line in html.unescape(soup.get_text("")).splitlines())
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


BLOCK_TAGS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"]


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()
