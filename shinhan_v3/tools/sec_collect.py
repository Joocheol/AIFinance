"""SEC EDGAR에서 JPMorgan 424B2 공시 원문(HTML)을 새로 받는다 (강사용, AI 호출 없음).

    uv run python shinhan_v3/tools/sec_collect.py all          # 목록 + 원문 (실행하면 연락 이메일을 묻는다)
    uv run python shinhan_v3/tools/sec_collect.py inventory    # 목록만
    uv run python shinhan_v3/tools/sec_collect.py download     # 원문만 (이어 받기)

범위: JPMorgan Chase & Co.(CIK 19617)와 발행 자회사 JPMorgan Chase Financial Company LLC(CIK 1665650)가
2026-01-01 ~ 2026-10-31 에 제출한 424B2. 같은 공시가 두 CIK에 함께 등록되므로 접수번호(accession)로 합친다.

SEC 공정 접근 규칙을 지킨다.
- User-Agent 에 운영자 연락처가 있어야 한다 (SEC_USER_AGENT 환경변수). 연락처는 어떤 파일에도 쓰지 않는다.
- 초당 요청 수를 --rate 이하로 (SEC 상한은 초당 10건). 403·429가 오면 전체를 즉시 멈춘다. 우회(프록시 등)는 하지 않는다.
- 이미 받은 파일은 다시 받지 않는다 (중단 후 이어 받기).

결과 (<out>, 기본 data/sec_v3):
  submissions/CIK*.json           SEC 제출 목록 원본
  filings.csv                     수집 대상 목록 (accession, 제출일, 등록 CIK, 원문 URL)
  html/<accession>.html           원문 HTML (SEC가 보내 준 바이트 그대로)
  download_log.csv                파일별 결과 (상태, 바이트, sha256, 받은 시각)
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CIKS = ("0000019617", "0001665650")
START, END = "2026-01-01", "2026-10-31"
FORM = "424B2"


class Blocked(RuntimeError):
    pass


class Sec:
    """초당 요청 수를 지키는 단일 창구. 403/429 이면 stop 을 세워 모든 작업을 멈춘다."""

    def __init__(self, rate: float):
        ua = os.environ.get("SEC_USER_AGENT", "")
        if "@" not in ua and sys.stdin.isatty():
            # 실행하는 사람이 직접 입력한다. 화면·파일 어디에도 다시 쓰지 않는다.
            email = input("SEC 연락 이메일 (요청 머리글에만 쓰고 저장하지 않음): ").strip()
            ua = f"AIFinance course research {email}"
        if "@" not in ua:
            sys.exit("연락 이메일이 필요합니다: 터미널에서 실행해 입력하거나 SEC_USER_AGENT 를 설정하세요 (SEC 공정 접근 규칙).")
        self.ua = ua
        self.gap = 1.0 / rate
        self.next = 0.0
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def _pace(self) -> None:
        with self.lock:
            wait = max(0.0, self.next - time.monotonic())
            self.next = max(self.next, time.monotonic()) + self.gap
        time.sleep(wait)

    def get(self, url: str, tries: int = 3) -> bytes:
        last = ""
        for attempt in range(tries):
            if self.stop.is_set():
                raise Blocked("stopped")
            self._pace()
            req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    b = r.read()
                if not b:
                    raise ValueError("empty response")
                return b
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    self.stop.set()
                    raise Blocked(f"HTTP {e.code} {url}")
                if e.code < 500:
                    raise
                last = f"HTTP {e.code}"
            except (OSError, ValueError) as e:
                last = f"{type(e).__name__}: {e}"[:120]
            time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"{tries}회 실패 (마지막 오류: {last}): {url}")


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def inventory(sec: Sec, out: Path) -> None:
    sub = out / "submissions"
    sub.mkdir(parents=True, exist_ok=True)
    by_acc: dict[str, dict] = {}
    for cik in CIKS:
        name = f"CIK{cik}.json"
        root = json.loads(sec.get(f"https://data.sec.gov/submissions/{name}"))
        (sub / name).write_text(json.dumps(root), encoding="utf-8")
        arrays = [root["filings"]["recent"]]
        for h in root["filings"].get("files", []):  # 오래된 제출은 별도 파일에 나뉘어 있다
            if h["filingFrom"] <= END and h["filingTo"] >= START:
                j = json.loads(sec.get(f"https://data.sec.gov/submissions/{h['name']}"))
                (sub / h["name"]).write_text(json.dumps(j), encoding="utf-8")
                arrays.append(j)
        for a in arrays:
            for i, form in enumerate(a["form"]):
                if form == FORM and START <= a["filingDate"][i] <= END:
                    acc = a["accessionNumber"][i]
                    r = by_acc.setdefault(acc, dict(accession=acc, filing_date=a["filingDate"][i],
                                                     primary_document=a["primaryDocument"][i], ciks=set()))
                    r["ciks"].add(cik)
    rows = []
    for acc, r in sorted(by_acc.items()):
        folder = acc.replace("-", "")
        rows.append(dict(accession=acc, filing_date=r["filing_date"], month=r["filing_date"][:7],
                         registrant_ciks=";".join(sorted(r["ciks"])), primary_document=r["primary_document"],
                         url=f"https://www.sec.gov/Archives/edgar/data/19617/{folder}/{r['primary_document']}"))
    write_csv(out / "filings.csv", rows, list(rows[0]))
    months = collections.Counter(r["month"] for r in rows)
    both = sum(";" in r["registrant_ciks"] for r in rows)
    print(f"424B2 {len(rows):,}건 (두 CIK에 함께 등록 {both:,}건)")
    print(json.dumps(dict(sorted(months.items())), ensure_ascii=False))


def download(sec: Sec, out: Path, workers: int) -> None:
    with (out / "filings.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    html = out / "html"
    html.mkdir(parents=True, exist_ok=True)
    log_path = out / "download_log.csv"
    done: dict[str, dict] = {}
    if log_path.exists():
        with log_path.open(encoding="utf-8") as f:
            done = {r["accession"]: r for r in csv.DictReader(f) if r["status"] == "ok"}
    todo = [r for r in rows if not (r["accession"] in done and (html / f"{r['accession']}.html").exists())]
    print(f"대상 {len(rows):,}건, 이미 받음 {len(rows) - len(todo):,}건, 받을 것 {len(todo):,}건", flush=True)
    fields = ["accession", "status", "bytes", "sha256", "retrieved_at", "url", "error"]
    results = dict(done)
    t0 = time.monotonic()

    def one(r: dict) -> dict:
        acc = r["accession"]
        # 같은 공시는 등록된 회사(CIK)마다 EDGAR 폴더가 있다. 기본은 모회사(19617) 폴더,
        # 서버 오류(5xx·시간 초과)로 못 받으면 함께 등록된 다른 회사 폴더의 같은 파일을 받는다 (SEC 공식 주소).
        urls = [r["url"]] + [r["url"].replace("/edgar/data/19617/", f"/edgar/data/{int(c)}/")
                             for c in r["registrant_ciks"].split(";") if int(c) != 19617]
        errors = []
        for url in urls:
            try:
                b = sec.get(url, tries=5)
            except Blocked as e:
                return dict(accession=acc, status="blocked" if "HTTP" in str(e) else "not_attempted", url=url, error=str(e))
            except Exception as e:  # noqa: BLE001
                errors.append(str(e)[:200])
                continue
            p = html / f"{acc}.html"
            p.with_suffix(".part").write_bytes(b)
            p.with_suffix(".part").replace(p)
            return dict(accession=acc, status="ok", bytes=len(b), sha256=hashlib.sha256(b).hexdigest(),
                        retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), url=url,
                        error=" / ".join(errors))
        return dict(accession=acc, status="failed", url=r["url"], error=" / ".join(errors)[:400])

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, r) for r in todo]
        for n, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            results[res["accession"]] = res
            if n % 500 == 0 or n == len(todo) or res["status"] == "blocked":
                write_csv(log_path, list(results.values()), fields)
                c = collections.Counter(x["status"] for x in results.values())
                el = time.monotonic() - t0
                print(f"{n:,}/{len(todo):,}  {el / 60:.1f}분  {dict(c)}", flush=True)
            if res["status"] == "blocked":
                print("SEC가 403/429로 막음 → 전체 중단", flush=True)
    write_csv(log_path, list(results.values()), fields)
    c = collections.Counter(x["status"] for x in results.values())
    print(f"끝: {dict(c)} / {(time.monotonic() - t0) / 60:.1f}분", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["inventory", "download", "all"])
    ap.add_argument("--out", type=Path, default=REPO / "data" / "sec_v3")
    ap.add_argument("--rate", type=float, default=4.0, help="초당 요청 수 상한 (SEC 상한 10)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sec = Sec(a.rate)
    if a.cmd in ("inventory", "all"):
        inventory(sec, out)
    if a.cmd in ("download", "all"):
        download(sec, out, a.workers)


if __name__ == "__main__":
    main()
