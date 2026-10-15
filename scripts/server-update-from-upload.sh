#!/usr/bin/env bash
set -euo pipefail

# Runs on the server. It receives an uploaded tar.gz package, updates the app
# directory in place, preserves server-only secrets/logs, rebuilds Docker, runs
# selected migrations, and checks backend health.

APP_DIR="${1:?用法: server-update-from-upload.sh /path/to/app /tmp/release.tar.gz}"
ARCHIVE="${2:?用法: server-update-from-upload.sh /path/to/app /tmp/release.tar.gz}"
STAMP="$(date +%Y%m%d_%H%M%S)"
RELEASE_DIR="/tmp/okk_release_${STAMP}"
BACKUP_DIR="${APP_DIR}/backups"
COMPOSE_FILE="docker-compose.prod.yml"
MIGRATIONS="${OKK_MIGRATIONS:-backend/migrations/012_add_strategy_api_config_binding.sql}"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

if [ ! -f "${ARCHIVE}" ]; then
  echo "找不到上传包: ${ARCHIVE}" >&2
  exit 1
fi

mkdir -p "${APP_DIR}" "${BACKUP_DIR}" "${RELEASE_DIR}"

if ! command -v rsync >/dev/null 2>&1; then
  echo "服务器缺少 rsync，请先安装: apt install -y rsync" >&2
  exit 1
fi

echo "==> 解压上传包"
tar -xzf "${ARCHIVE}" -C "${RELEASE_DIR}"

if [ ! -f "${RELEASE_DIR}/${COMPOSE_FILE}" ]; then
  echo "上传包里没有 ${COMPOSE_FILE}，停止更新" >&2
  exit 1
fi

cd "${APP_DIR}"

if [ ! -f ".env" ]; then
  echo "服务器 ${APP_DIR}/.env 不存在。为避免覆盖密钥，本脚本不会从本地上传 .env。" >&2
  echo "请先在服务器创建 .env，可参考 .env.prod 或 .env.prod.example。" >&2
  exit 1
fi

echo "==> 备份当前代码和数据库"
tar -czf "${BACKUP_DIR}/source_${STAMP}.tar.gz" \
  --exclude='./backups' \
  --exclude='./backend/logs' \
  --exclude='./nginx/logs' \
  --exclude='./frontend/node_modules' \
  --exclude='./backend/venv' \
  . >/dev/null 2>&1 || true

if compose -f "${COMPOSE_FILE}" ps postgres >/dev/null 2>&1; then
  compose -f "${COMPOSE_FILE}" up -d postgres >/dev/null
  sleep 3
  docker exec okk_postgres pg_dump -U okk_user okk_quant > "${BACKUP_DIR}/db_${STAMP}.sql" || true
fi

echo "==> 同步新代码，保留服务器密钥和日志"
rsync -a --delete \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='.env.prod' \
  --exclude='backups/' \
  --exclude='backend/logs/' \
  --exclude='nginx/logs/' \
  "${RELEASE_DIR}/" "${APP_DIR}/"

mkdir -p backend/logs nginx/logs

echo "==> 启动基础服务"
compose -f "${COMPOSE_FILE}" up -d postgres redis

echo "==> 执行数据库迁移"
if [ -n "${MIGRATIONS}" ]; then
  IFS=',' read -ra MIGRATION_LIST <<< "${MIGRATIONS}"
  for migration in "${MIGRATION_LIST[@]}"; do
    migration="$(echo "${migration}" | xargs)"
    if [ -z "${migration}" ]; then
      continue
    fi
    if [ ! -f "${migration}" ]; then
      echo "跳过不存在的迁移: ${migration}"
      continue
    fi
    echo "  - ${migration}"
    docker cp "${migration}" "okk_postgres:/tmp/$(basename "${migration}")"
    docker exec okk_postgres psql -U okk_user -d okk_quant -v ON_ERROR_STOP=1 -f "/tmp/$(basename "${migration}")"
  done
fi

echo "==> 重建并启动应用容器"
compose -f "${COMPOSE_FILE}" up -d --build backend frontend nginx

echo "==> 检查后端健康状态"
for i in $(seq 1 18); do
  if curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "后端健康检查通过"
    rm -rf "${RELEASE_DIR}" "${ARCHIVE}"
    exit 0
  fi
  echo "等待后端启动... ${i}/18"
  sleep 5
done

echo "后端健康检查失败，最近日志如下:" >&2
compose -f "${COMPOSE_FILE}" logs --tail=120 backend >&2
exit 1
