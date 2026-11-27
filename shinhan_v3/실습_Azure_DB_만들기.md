# 실습: Azure에 내 DB 만들기 — CLI, 포털, Claude 세 가지 방법

**목표**: 같은 것(Azure PostgreSQL 서버)을 세 가지 방법으로 만들어 보고, 방법마다 무엇이 보이고 무엇이 남는지 비교합니다. 그다음 내가 바꾼 10월 텍스트를 내 DB에 넣고, 강사의 **공용 상품 DB**와 이어 봅니다.

| 순서 | 방법 | 누가 | 시간 |
|---|---|---|---|
| A | **CLI**: 명령 한 줄에 설정 전부 | 강사 시연 (VS Code 터미널) | 10분 |
| B | **포털**: 화면에서 칸을 하나씩 골라 만들기 → **내 DB** | 나 | 20분 (만들어지는 6분 동안 C를 본다) |
| C | **Claude**: 말로 요구사항 → Claude가 명령 스크립트 → 읽고 실행 → 비교 후 삭제 | 강사 시연 (VS Code Claude Code) | 10분 |
| D | 내 DB에 10월 텍스트 넣고 VS Code에서 들여다보기 | 나 | 10분 |
| E | 공용 상품 DB 읽고 내 공시와 이어 보기 | 나 | 5분 |

**도구** (사전 준비에서 설치): VS Code, VS Code의 **Claude Code** 확장, **Azure CLI**(`az`), VS Code의 **PostgreSQL** 확장(Microsoft, `ms-ossdata.vscode-pgsql`). VS Code 터미널에서 `az login`을 한 번 해 둡니다.

---

## A. 강사 시연: CLI로 만들기

강사가 VS Code 터미널에서 [`create_pg.sh`](tools/create_pg.sh)를 실행합니다. 명령 하나의 옵션이 곧 설정입니다. 아래 표를 보며 따라 읽습니다. B에서 포털 칸과 하나씩 맞춰 봅니다.

```bash
az postgres flexible-server create \
  --resource-group jpm-course --name jpm-pg-demo --location japaneast \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 --storage-auto-grow Disabled --version 16 \
  --admin-user jpmadmin --admin-password <실행 중에 입력> \
  --public-access <내 공인 IP> --backup-retention 7 --yes
az postgres flexible-server parameter set -g jpm-course -s jpm-pg-demo -n azure.extensions -v VECTOR
```

| CLI 옵션 | 뜻 | 포털에서는 (B에서 채울 칸) | 내가 찾은 화면 위치 |
|---|---|---|---|
| `--resource-group jpm-course` | 묶음 이름. 지울 때 통째로 | 기본 사항 → 리소스 그룹 | |
| `--name` | 서버 이름 = 주소의 앞부분 (전 세계에서 유일) | 기본 사항 → 서버 이름 | |
| `--location japaneast` | 지역. 한국 지역은 무료 등급이 안 만들어짐 | 기본 사항 → 지역 | |
| `--version 16` | PostgreSQL 버전 | 기본 사항 → 버전 | |
| `--tier Burstable --sku-name Standard_B1ms` | 가장 작은 사양 (무료 계정 12개월 무료) | 컴퓨팅 + 스토리지 → 서버 구성 | |
| `--storage-size 32 --storage-auto-grow Disabled` | 저장 공간 32GB, 자동으로 늘리지 않음 | 컴퓨팅 + 스토리지 | |
| `--backup-retention 7` | 백업 7일 보관 | 컴퓨팅 + 스토리지 → 백업 | |
| `--admin-user/--admin-password` | 관리자 계정 | 기본 사항 → 인증 | |
| `--public-access <IP>` | 이 IP에서만 접속 허용 (방화벽) | 네트워킹 → 방화벽 규칙 | |
| `parameter set azure.extensions VECTOR` | 벡터 검색 확장(pgvector) 허용 | 만든 뒤 → 서버 매개변수 | |

> CLI의 장점: 같은 명령을 다시 실행하면 같은 서버가 나온다. 기록이 남는다. 단점: 옵션 이름을 알아야 한다.

## B. 포털에서 직접 만들기 → 내 DB

[portal.azure.com](https://portal.azure.com) → 위쪽 검색창 **Azure Database for PostgreSQL** → **유연한 서버(Flexible server)** → **만들기**.

1. **기본 사항**
   - 리소스 그룹: 새로 만들기 → `jpm-course`
   - 서버 이름: `jpm-pg-<내 영문 이니셜>-<숫자 2자리>` (예: `jpm-pg-hgd-07`). 이미 있으면 숫자를 바꿉니다.
   - 지역: **Japan East** · PostgreSQL 버전: **16**
   - 워크로드 유형: **개발** → **컴퓨팅 + 스토리지 구성**: 버스트 가능(Burstable), **Standard_B1ms**, 저장소 **32GiB**, 저장소 자동 증가 **끔**
     - **주의**: 기본값이 **B2s**(2 vCores, 4 GiB)로 잡힙니다. **서버 구성(Configure server)**을 눌러 **Standard_B1ms (1 vCore, 2 GiB)**로 바꿉니다. 무료 계정의 무료 대상은 B1ms뿐입니다.
   - 고가용성: 끔
   - 인증: **PostgreSQL 인증만**, 관리자 이름 `jpmadmin`, 비밀번호 12자 이상(종이에 적기)
2. **네트워킹** → 방화벽 규칙: **+ 현재 클라이언트 IP 주소 추가(Add current client IP address)** 를 한 번 누릅니다. 아래 표에 내 IP 한 줄이 생기면 됩니다.
   - 바로 옆의 **+ 0.0.0.0 - 255.255.255.255 추가**는 누르지 않습니다(전 세계에 열림).
   - **Azure 서비스의 공용 액세스 허용**은 체크하지 않습니다.
3. **검토 + 만들기** → 화면에 나온 **예상 비용**을 확인하고(B1ms면 정가 월 $23.40, 그 아래에 무료 750시간·32GB 표시) → **만들기**. 약 6분 걸립니다. 기다리는 동안 강사의 C 시연을 봅니다.
4. 다 만들어지면 → 리소스로 이동 → 왼쪽 **서버 매개변수** → 검색 `azure.extensions` → **VECTOR** 체크 → 저장

| 확인 | 내 값 |
|---|---|
| 서버 이름 | |
| 주소 (개요의 "서버 이름" = `….postgres.database.azure.com`) | |
| 예상 월 비용 (검토 화면) | |
| 만드는 데 걸린 시간 | |

## C. 강사 시연: Claude로 만들기 → 비교 → 삭제

강사가 VS Code의 Claude Code 패널에 **말로** 요구사항을 주고, Claude가 쓴 스크립트를 함께 읽은 뒤 실행합니다. 실행 전에 무엇을 확인하는지 봅니다.

```
Azure CLI 로 PostgreSQL 유연한 서버를 하나 만드는 스크립트 make_pg2.sh 를 써줘. 실행하지는 마.
조건: 리소스 그룹 jpm-course, 지역 japaneast, 서버 이름 jpm-pg-demo-c,
Burstable Standard_B1ms, 저장소 32GB 자동 증가 끔, PostgreSQL 16, 관리자 jpmadmin,
방화벽은 이 노트북의 공인 IP만(서버를 만들 때 --public-access 에 그 IP를 넣어 한 번에), azure.extensions 에 VECTOR 허용.
비밀번호는 스크립트가 실행될 때 터미널에서 직접 입력하게 하고(화면에 안 보이게), 어디에도 저장하지 마.
명령마다 무엇을 하는지 한 줄 주석을 달아줘.
az 옵션 이름은 기억으로 쓰지 말고, 쓰는 명령마다 이 노트북에서 `az <명령> --help` 를 실행해 확인한 뒤 써. --output 옵션은 붙이지 마.
```

> 괄호 안의 방화벽 지시와 마지막 줄이 없으면 Claude가 서버만 만들고 방화벽 단계에서 멈추는 일이 잦습니다. 옛 문법(`firewall-rule create -n <서버>`)을 쓰거나, `--public-access None`으로 만든 뒤 규칙을 따로 추가하려 하기 때문입니다. `None`은 도움말 설명과 달리 공개 접근이 꺼진 서버를 만들어 규칙을 추가할 수 없습니다(az 2.92). `--output table`을 서버 만들기에 붙이면 서버는 생기지만 "Table output unavailable" 오류로 스크립트가 멈춰 VECTOR가 빠집니다.

시연 순서
1. Claude가 쓴 스크립트를 A의 명령과 한 줄씩 대조합니다. 다른 옵션이 있으면 Claude에게 왜 다른지 묻습니다.
2. 강사가 VS Code 터미널에서 실행합니다(비밀번호는 터미널에 직접 입력).
3. Claude에게 *"A·C 두 서버의 설정을 az CLI 로 읽어 비교표를 만들고 다른 칸을 표시해줘"* → 비교표를 같이 봅니다.
4. 두 번째 서버를 지웁니다: `az postgres flexible-server delete -g jpm-course -n jpm-pg-demo-c --yes`

| 시연을 보며 적기 | |
|---|---|
| Claude 스크립트가 A 명령과 다른 옵션 | |
| 실행 전에 강사가 확인한 것 | |
| 세 방법(CLI·포털·Claude)이 각각 남기는 기록 | |

## D. 내 DB에 10월 텍스트 넣기

1. 사전 준비 때 만든 `jpm_kit/.env`를 **열어서** `PGHOST`(B의 주소)와 `PGPASSWORD` 두 줄을 **직접** 채웁니다. `.env.example`을 다시 복사하면 `SEC_CONTACT`가 지워지니 복사하지 않습니다. Claude에게 보여 주지 않습니다.
2. Claude Code 패널:
```
jpm_kit/load_text.py 가 무엇을 하는지 설명해줘(.env 는 열지 마). 특히 텍스트를 어떤 단위로 잘라 chunks 에 넣는지,
'공통 문구'를 왜 한 번만 넣는지. 설명이 끝나면 uv run jpm_kit/load_text.py 를 실행해줘.
```
3. VS Code 왼쪽 **PostgreSQL** 아이콘 → 새 연결 → 내 서버 주소·`jpmadmin`·비밀번호 → `postgres` 데이터베이스 → 표 `filings`, `chunks`를 열어 봅니다. 새 쿼리 창에서:
```sql
select accession, chars, left(body, 120) from filings order by chars limit 5;
select is_boilerplate, count(*), avg(length(body))::int from chunks group by 1;
```

| 표 | 행 수 | 1행은 무엇인가 |
|---|---|---|
| filings | | |
| chunks (공통 문구 수) | | |

## E. 공용 상품 DB 읽기

상품 표는 강사가 10개월 공시로 만든 것을 **모두 같이** 씁니다(읽기 전용). 접속 정보는 아래와 같고, 키트의 `.env.example`에 이미 들어 있습니다. `.env`에 이 네 줄이 있는지 확인합니다(없으면 복사해 넣기).

```
SHARED_HOST=jpm-shared-d32c.postgres.database.azure.com
SHARED_USER=student_ro
SHARED_PASSWORD=20261128
SHARED_DATABASE=jpm
```

> 읽기 전용 계정이라 표를 바꿀 수 없고, **연세대 네트워크(교내 와이파이·유선)에서만** 접속됩니다. 휴대폰 핫스팟이나 집에서는 연결되지 않습니다.

그다음:
```
uv run jpm_kit/shared_products.py
```

| 확인 | 내 값 |
|---|---|
| 공용 상품 표의 상품 수 / 공시 수 | |
| 원금 확인 상품 / 합계 | |
| 내 10월 공시 중 상품이 있는 공시 / 없는 공시 | |

## 생각해 보기

1. 세 방법 중 "어제와 똑같은 서버를 내일 다시 만들기"에 가장 좋은 것은? 감사(누가 무엇을 만들었나)에는?
2. Claude가 만든 스크립트를 실행하기 전에 꼭 확인해야 할 것 두 가지는? (C 시연에서 본 것)
3. 내 10월 공시인데 상품 표에 상품이 없는 공시는 무엇일까요?
4. 공용 상품 DB가 읽기 전용인 이유는?
