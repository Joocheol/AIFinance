"""받은 SEC 원문 HTML → 평문 텍스트 (강사용, AI 호출 없음).

    uv run python shinhan_v3/tools/to_text.py            # 지금 있는 HTML 을 모두 변환
    uv run python shinhan_v3/tools/to_text.py --watch    # 내려받는 동안 새 파일을 계속 변환, 다 받으면 끝

입력  <out>/html/<accession>.html   (sec_collect.py 가 받은 것)
출력  <out>/text/<accession>.txt    (변환기: src/aifinance/htmltext.py)
      <out>/text_checks.csv         (파일별 HTML 종류, 검사 1·2 결과)

검사 (파일마다)
  1 글자 보존: HTML 화면 글자와 변환 결과에서 공백·'|'를 뺀 글자열이 순서까지 같다.
  2 숫자 온전함: 날짜·금액·비율이 줄바꿈으로 끊기지 않고, 원문에 없는 공백이 끼지 않는다.
  (검사 구현은 shinhan/tools/text_v2.py 의 check_one 을 그대로 쓴다.)
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("text_v2", REPO / "shinhan" / "tools" / "text_v2.py")
tv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tv)  # check_one(raw) -> (검사 결과, 변환 텍스트)

FIELDS = ["accession", "kind", "chars", "check1", "check2_defects", "check1_at", "check2_examples"]


def one(args: tuple[str, str]) -> dict:
    src, dst = args
    raw = Path(src).read_bytes()
    res, text = tv.check_one(raw)
    tmp = Path(dst).with_suffix(".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dst)
    return dict(accession=Path(src).stem, kind=res["kind"], chars=len(text), check1="ok" if res["c1"] else "FAIL",
                check2_defects=len(res["c2"]), check1_at=str(res.get("c1_at", ""))[:300],
                check2_examples=" || ".join(x[1] for x in res["c2"][:3])[:500])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / "data" / "sec_v3")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--idle", type=int, default=600, help="--watch: 새 파일이 이 초 동안 없으면 끝")
    a = ap.parse_args()
    out = a.out.resolve()
    html, text = out / "html", out / "text"
    text.mkdir(parents=True, exist_ok=True)
    log_path = out / "text_checks.csv"
    rows: dict[str, dict] = {}
    if log_path.exists():
        with log_path.open(encoding="utf-8") as f:
            rows = {r["accession"]: r for r in csv.DictReader(f)}
    with (out / "filings.csv").open(encoding="utf-8") as f:
        target = sum(1 for _ in csv.DictReader(f))
    t0, last_new = time.monotonic(), time.monotonic()
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 2)) as ex:
        while True:
            todo = []
            for p in sorted(html.glob("*.html")):
                q = text / f"{p.stem}.txt"
                if p.stem not in rows or not q.exists() or q.stat().st_mtime < p.stat().st_mtime:
                    todo.append((str(p), str(q)))
            if todo:
                last_new = time.monotonic()
                for r in ex.map(one, todo, chunksize=8):
                    rows[r["accession"]] = r
                tmp = log_path.with_suffix(".tmp")
                with tmp.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDS)
                    w.writeheader()
                    w.writerows(sorted(rows.values(), key=lambda r: r["accession"]))
                tmp.replace(log_path)
                vals = list(rows.values())
                pdf = sum(r["kind"] == "pdf" for r in vals)
                f1 = sum(r["check1"] != "ok" for r in vals)
                f2 = sum(int(r["check2_defects"]) > 0 for r in vals)
                print(f"변환 {len(vals):,}/{target:,}건 (PDF 변환형 {pdf:,})  검사1 실패 {f1}  검사2 실패 {f2}  "
                      f"{(time.monotonic() - t0) / 60:.1f}분", flush=True)
            if not a.watch or len(rows) >= target or time.monotonic() - last_new > a.idle:
                break
            time.sleep(20)
    print("끝", flush=True)


if __name__ == "__main__":
    main()
