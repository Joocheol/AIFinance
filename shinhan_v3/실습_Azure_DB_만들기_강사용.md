# 강사용: Azure에 내 DB 만들기

학생용: [실습_Azure_DB_만들기.md](실습_Azure_DB_만들기.md)

## 수업 전 준비

| 할 일 | 방법 | 확인 |
|---|---|---|
| 시연 스크립트 | [`tools/create_pg.sh`](tools/create_pg.sh). VS Code 터미널, `az login` 미리. 당일 서버 이름 `jpm-pg-demo-<날짜>` | |
| **공용 상품 DB** | 아래 "공용 상품 DB 만들기" | |
| 공용 DB 접속 정보 배포 | `SHARED_HOST/USER/PASSWORD/DATABASE` 네 값. 칠판 또는 Dropbox 텍스트 파일 (채팅·메신저로 보내지 않음) | |
| 학생 노트북 | VS Code + Claude Code 확장 + Azure CLI + PostgreSQL 확장 설치, `az login` 성공 (사전 과제) | |

## 공용 상품 DB 만들기 (강사 구독, 한 번)

1. 서버: `bash shinhan_v3/tools/create_pg.sh jpm-shared` (강사 IP만 열림)
2. 상품 표 적재: 10개월 상품 표(2026-01~10, 강사가 만든 것)를 `jpm` 데이터베이스의 `products` 표로. `filing_date`, `issue_date` 등 날짜는 date 형.
3. 읽기 전용 계정:
   ```sql
   create role student_ro login password '<새 비밀번호>';
   grant connect on database jpm to student_ro;
   grant usage on schema public to student_ro;
   grant select on products to student_ro;
   ```
4. 방화벽: 학생마다 IP가 다르므로 **모든 IP 허용**(0.0.0.0–255.255.255.255) + 읽기 전용 계정 + 강한 비밀번호. 공개 SEC 데이터라 이 정도로 충분하다고 본다. 수업이 끝나면 규칙을 지우거나 서버를 멈춘다.
5. 확인: 학생 키트의 `shared_products.py`를 강사 노트북에서 한 번 실행.

## 진행 포인트

- **A (CLI 시연)**: 실행 직후 옵션 표를 같이 읽는다. 만들어지는 6분 동안 B를 시작시킨다. 끝나면 `show` 결과의 주소(FQDN)를 가리키며 "이게 .env의 PGHOST".
- **B (포털)**: **기본값이 B2s**로 잡힌다 → "서버 구성"에서 B1ms로 바꿨는지 돌아다니며 확인(B2s는 무료 아님, 약 $49/월). 방화벽은 "+ 현재 클라이언트 IP 주소 추가" 버튼 하나만(옆의 0.0.0.0–255.255.255.255 버튼 주의). 검토 화면의 **예상 비용**을 꼭 보게 한다(B1ms 정가 $23.40/월, 무료 한도 표시). 무료 계정 B1ms는 12개월 무료 대상이지만 화면에는 정가가 표시될 수 있다. 서버 매개변수 VECTOR를 빼먹는 학생이 많다 → D에서 `load_text.py`가 경고를 낸다.
- **C (Claude)**: 강사 창에서 **빈 폴더**(예: `~/Documents/jpm-demo-c`)를 열고 시연한다. 저장소를 연 채로 하면 Claude가 `create_pg.sh`를 보고 따라 쓴다(3차 리허설). 비밀번호를 채팅에 쓰지 않게 하는 것이 핵심. Claude가 비밀번호를 스크립트에 넣거나 인자로 받게 쓰면 "요구사항 위반"으로 고치게 한다. 비교표에서 흔한 차이: Claude가 `--storage-auto-grow`를 빼거나, `--public-access`에 `0.0.0.0`(Azure 서비스 허용)을 더하는 경우. 프롬프트의 "(서버를 만들 때 --public-access 에 그 IP를 넣어 한 번에)"와 마지막 줄(`--help`로 확인)을 빼면 서버만 생기고 방화벽에서 멈춘다. 원인은 둘: `firewall-rule create -n <서버>` 옛 문법(3차 리허설), `--public-access None`으로 만든 뒤 규칙 추가 → None은 실제로 공개 접근 Disabled라 규칙 추가 불가(11/26, az 2.92). 그래도 멈추면 오류를 Claude에게 보여 주고 남은 단계만 실행하게 한다.
  두 번째 서버는 반드시 삭제(무료 계정이라도 두 대째 저장소 32GB는 과금될 수 있다).
- **D (적재)**: 학생이 `.env.example`을 다시 복사해 `SEC_CONTACT`를 지우지 않게(기존 `.env`에 두 줄만 채움).
- **D 결과**: 10월 1,859건 → filings 1,859 / chunks 63,732(공통 문구 182), 69초. 행 수가 다르면 `sec_oct/text`가 덜 만들어진 것(to_text.py 다시).
- **E (공용 DB)**: 내 10월 공시 중 상품이 없는 공시 = 예비 가격 공시, 공통 설명서 등. 다음 실습(문서 ≠ 상품)으로 이어진다.

## 정답 (2026-11-24 리허설)

| 항목 | 값 |
|---|---|
| CLI로 서버 생성 시간 | 6분 10초 (`create_pg.sh`로 공용 DB를 만들 때) |
| 10월 filings / chunks / 공통 문구 | 1,859 / 63,732 / 182 |
| 적재 시간 | 69초 (DB 183MB) |
| 공용 상품 표: 상품 / 공시 / 원금 확인 / 합계 | 8,868 / 8,803 / 8,696 / $21.29B |
| 10월 공시 중 상품이 있는 공시 / 없는 공시 | 828 / 1,031 |

**공용 상품 DB (실제)**: `jpm-shared-d32c.postgres.database.azure.com`, 리소스 그룹 `jpm-instructor`, 데이터베이스 `jpm`, 표 `products`, 읽기 전용 `student_ro`(쓰기 시도 → InsufficientPrivilege 확인). 방화벽: 연세대 165.132.0.0–165.132.255.255 (`yonsei-net`).
2026-11-25: 무료 체험 구독(30일 크레딧)에서 **연세 `Azure for Students` 구독**으로 옮겨 같은 이름으로 다시 만들었다(주소 그대로, 이름이 풀리기까지 삭제 후 약 4분). 관리자 비밀번호는 강사 노트북 `~/.config/jpm-instructor/adminpw`.
2026-11-26: 리소스 그룹 `jpm-instructor`에 삭제 잠금 `keep-shared-db`(CanNotDelete). 서버·방화벽 규칙을 지우려면 먼저 `az lock delete -g jpm-instructor -n keep-shared-db` (12월 5일 수업 뒤).

## 시험 기록

- 2026-11-24: `load_text.py`·`shared_products.py`를 Azure 시험 서버(Japan East)에서 1월 공시 40건으로 실행. 40건 → chunks 1,916(공통 문구 40), 1초. 공용 DB 자리는 v2 상품 표(10,542개)로 대신해 읽기 확인.
- `create_pg.sh`로 공용 DB 서버를 실제로 만들었다(6분 10초). 처음 실행 때 마지막 `--query`가 한글 이름표를 받지 않아 실패 → 영어 이름표로 고침(서버 생성은 정상).
