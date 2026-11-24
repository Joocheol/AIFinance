#!/usr/bin/env bash
# 강사 시연: Azure CLI 로 PostgreSQL 서버 하나 만들기 (VS Code 터미널에서).
#   bash shinhan_v3/tools/create_pg.sh <서버이름>      예: bash shinhan_v3/tools/create_pg.sh jpm-pg-demo
# 먼저 `az login`. 비밀번호는 실행 중에 묻고, 화면·파일에 남기지 않는다.
# 포털에서 학생이 고르는 칸과 이 명령의 옵션이 하나씩 대응한다 (실습지 표 참고).
set -euo pipefail

NAME="${1:?서버 이름을 주세요 (소문자·숫자·하이픈, 전 세계에서 유일)}"
RG="${RG:-jpm-course}"            # 리소스 그룹
LOC="${LOC:-japaneast}"           # 지역: 한국 지역은 무료 등급 PostgreSQL 이 만들어지지 않는다
ADMIN="${ADMIN:-jpmadmin}"
MYIP="$(curl -s https://api.ipify.org)"   # 이 노트북의 공인 IP (방화벽 허용)

read -r -s -p "DB 관리자 비밀번호 (12자 이상, 대·소문자·숫자): " PW; echo

az group create -n "$RG" -l "$LOC" -o none
echo "리소스 그룹 $RG ($LOC) 준비"

time az postgres flexible-server create \
  --resource-group "$RG" --name "$NAME" --location "$LOC" \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 --storage-auto-grow Disabled \
  --version 16 \
  --admin-user "$ADMIN" --admin-password "$PW" \
  --public-access "$MYIP" \
  --backup-retention 7 \
  --yes -o none

# pgvector 를 쓸 수 있게 허용 (포털: 서버 매개변수 → azure.extensions → VECTOR)
az postgres flexible-server parameter set -g "$RG" -s "$NAME" -n azure.extensions -v VECTOR -o none

az postgres flexible-server show -g "$RG" -n "$NAME" \
  --query "{name:name, state:state, version:version, sku:sku.name, tier:sku.tier, storageGB:storage.storageSizeGb, host:fullyQualifiedDomainName}" -o table
az postgres flexible-server firewall-rule list -g "$RG" -s "$NAME" --query "[].{rule:name, start:startIpAddress, end:endIpAddress}" -o table
