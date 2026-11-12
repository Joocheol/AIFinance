# 정답셋(Gold Set) 라벨링 지침

> Claude Desktop Code 탭에서 사용하는 프롬프트입니다. 대상 파일 목록만 바꿔 붙여 넣으세요.

---

너는 구조화 상품 텀시트를 정밀하게 읽는 데이터 라벨러다.
아래 공시 평문 파일 각각을 읽고, `src/aifinance/schema.py`의 `TermSheet` 스키마에 맞는 JSON을 만들어 `gold/<접수번호>.json`으로 저장해줘.

**대상 파일**: `data/text/<접수번호>.txt` (목록은 아래)

## 규칙

1. **원문에 적힌 값만** 쓴다. 추측·계산으로 채우지 않는다. 없으면 `null`.
   - 예외: `coupon_rate_pa`는 "per annum" 값이 원문에 있으면 그것을, 월/분기 쿠폰만 있으면 연 환산값을 쓴다.
2. 비율은 소수: 70.00% → `0.70`, 연 18.00% → `0.18`, 2.17배 → `2.17`.
3. 날짜는 `YYYY-MM-DD`. "On or about September 10, 2026" → `2026-09-10`.
4. `principal_amount_usd`: 표지 또는 "Aggregate principal amount"의 총 발행금액.
5. `estimated_value_per_1000`: "The estimated value of the notes … was $XXX.XX per $1,000" 의 값.
6. `product_family` 판단 기준:
   | 값 | 판단 기준 |
   |---|---|
   | `autocall_contingent_coupon` | 기초자산 수준으로 자동조기상환 + 조건부 쿠폰 |
   | `issuer_call_contingent_coupon` | 발행사가 재량으로 조기상환(“we may redeem”) + 조건부 쿠폰 |
   | `autocall_call_premium` | 자동조기상환되며 쿠폰 대신 상환 프리미엄 지급 (Review Notes 등) |
   | `leveraged_buffer` | 상승 참여(레버리지) + 하방 버퍼 |
   | `leveraged_barrier` | 상승 참여 + 하방 배리어(트리거) |
   | `dual_directional` | 일정 범위 하락 시 하락률만큼 양(+)의 수익 |
   | `digital` | 조건 충족 시 고정 디지털 수익 |
   | `principal_protected` | 만기 원금 보장 |
   | `other` | 위에 해당하지 않음 |
   - 여러 특징이 겹치면 **수익 구조를 가장 잘 설명하는 하나**를 고른다. (예: Dual Directional + Buffer → `dual_directional`)
7. `downside_type`: 배리어 아래로 떨어지면 처음부터 1:1 손실 → `barrier`, 버퍼만큼 손실을 흡수 → `buffer`.
8. `basket_type`: 기초자산 1개 → `single`, "Least/Lesser Performing" → `worst_of`, 비중이 있는 바스켓 → `weighted_basket`.
9. `coupon_frequency`·`autocall_frequency`는 "monthly" 같은 단어가 없으면 **관찰일 목록의 간격**으로 판단해도 된다.
10. 디지털 상품에서 디지털 수익이 곧 최대 수익이어도 `cap_pct`는 원문에 "Maximum Return" 같은 정의 항목이 있을 때만 채운다.
11. 계단식(step-down) 조기상환 기준이나 회차별 상환 프리미엄처럼 스키마에 칸이 없는 정보는 "애매한 항목" 보고에 적는다.
12. 각 JSON 끝에 `"_evidence"` 객체를 추가해, 숫자·날짜 필드마다 근거가 된 원문 구절(40자 이내)을 적는다. (스키마 검증 시에는 제외)

## 완료 후

- `uv run python -c "..."`로 각 JSON이 `TermSheet.model_validate`를 통과하는지 확인하고 결과를 보고해줘.
- 판단이 애매했던 항목은 파일별로 따로 알려줘.
