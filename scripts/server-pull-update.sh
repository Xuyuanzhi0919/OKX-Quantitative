#!/usr/bin/env bash
set -euo pipefail

# Runs on the server: pull registry images, run migrations, restart Docker services.
#
# Example:
#   OKK_BACKEND_IMAGE=registry/okk-backend:v1 \
#   OKK_FRONTEND_IMAGE=registry/okk-frontend:v1 \
#   ./scripts/server-pull-update.sh /opt/1panel/apps/okk-trading

APP_DIR="${1:?用法: server-pull-update.sh /path/to/app}"
COMPOSE_FILE="docker-compose.prod.yml"
MIGRATIONS="${OKK_MIGRATIONS:-backend/migrations/012_add_strategy_api_config_binding.sql}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${APP_DIR}/backups"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

cd "${APP_DIR}"

if [ ! -f ".env" ]; then
  echo "服务器 ${APP_DIR}/.env 不存在" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

echo "==> 备份数据库"
compose -f "${COMPOSE_FILE}" up -d postgres >/dev/null
sleep 3
docker exec okk_postgres pg_dump -U okk_user okk_quant > "${BACKUP_DIR}/db_${STAMP}.sql" || true

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

echo "==> 拉取新镜像"
compose -f "${COMPOSE_FILE}" pull backend frontend

echo "==> 重启应用容器"
compose -f "${COMPOSE_FILE}" up -d --no-build backend frontend nginx

echo "==> 检查后端健康状态"
for i in $(seq 1 18); do
  if curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "后端健康检查通过"
    exit 0
  fi
  echo "等待后端启动... ${i}/18"
  sleep 5
done

echo "后端健康检查失败，最近日志如下:" >&2
compose -f "${COMPOSE_FILE}" logs --tail=120 backend >&2
exit 1
