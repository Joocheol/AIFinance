# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg[binary]"]
# ///
"""강사의 공용 상품 DB(읽기 전용)를 읽고, 내 DB의 10월 공시와 이어 본다.

    uv run jpm_kit/shared_products.py

공용 DB: 강사가 10개월(2026-01~10) 공시로 만든 상품 표 products. 모두 같은 표를 읽는다.
내 DB: 내가 받은 10월 공시(filings). 두 DB 는 서로 다른 서버라 SQL 로 바로 join 할 수 없다.
      → accession 으로 이어 본다: 내 10월 공시 중 상품 표에 상품이 있는 공시는 몇 건?
"""

import kit_db


def main() -> None:
    shared = kit_db.connect("SHARED")
    sc = shared.cursor()
    print("== 공용 상품 DB")
    print(kit_db.table(sc, """select count(*)::int as 상품, count(distinct accession)::int as 공시,
                                    count(principal)::int as 원금확인, round((sum(principal)/1e9)::numeric, 2) as 원금합계_십억달러
                             from products"""))
    print()
    print(kit_db.table(sc, """select to_char(filing_date, 'YYYY-MM') as 제출월, count(*)::int as 상품
                             from products group by 1 order by 1"""))
    sc.execute("select distinct accession from products where to_char(filing_date, 'YYYY-MM') = '2026-10'")
    oct_prod = {r[0] for r in sc.fetchall()}

    mine = kit_db.connect().cursor()
    mine.execute("select accession from filings")
    my_acc = {r[0] for r in mine.fetchall()}
    print("\n== 내 10월 공시와 이어 보기 (accession 기준)")
    print(f"내 10월 공시 {len(my_acc):,}건 중 상품 표에 상품이 있는 공시 {len(my_acc & oct_prod):,}건")
    print(f"상품이 없는 공시 {len(my_acc - oct_prod):,}건 → 예비·공통 설명서 등 (다음 실습에서 확인)")
    if oct_prod - my_acc:
        print(f"상품 표에는 있는데 내 DB에 없는 10월 공시 {len(oct_prod - my_acc):,}건 → 내가 덜 받았는지 확인")


if __name__ == "__main__":
    main()
