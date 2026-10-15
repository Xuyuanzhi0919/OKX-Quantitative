#!/usr/bin/env bash
set -euo pipefail

# Roll back server code to a specific git ref and rebuild Docker services.
# Usage:
#   ./scripts/server-rollback.sh /opt/1panel/apps/okk-trading HEAD~1
#   ./scripts/server-rollback.sh /opt/1panel/apps/okk-trading 27cd196

APP_DIR="${1:?用法: server-rollback.sh /path/to/app [git_ref]}"
TARGET_REF="${2:-HEAD~1}"
COMPOSE_FILE="docker-compose.prod.yml"
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
mkdir -p "${BACKUP_DIR}"

echo "==> 当前版本"
git --no-pager log --oneline -1

echo "==> 备份 .env 和当前版本号"
cp .env "${BACKUP_DIR}/env_${STAMP}.bak" 2>/dev/null || true
git rev-parse HEAD > "${BACKUP_DIR}/commit_${STAMP}.txt"

echo "==> 回滚到: ${TARGET_REF}"
git fetch origin main || true
git reset --hard "${TARGET_REF}"

echo "==> 恢复服务器 .env"
cp "${BACKUP_DIR}/env_${STAMP}.bak" .env 2>/dev/null || true

echo "==> 重建并启动 Docker"
compose -f "${COMPOSE_FILE}" up -d --build

echo "==> 健康检查"
for i in $(seq 1 18); do
  if curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "回滚完成，后端健康检查通过"
    echo "注意：数据库不会自动回滚。如本次发布执行过破坏性迁移，请人工检查数据库。"
    exit 0
  fi
  echo "等待后端启动... ${i}/18"
  sleep 5
done

echo "后端健康检查失败，最近日志如下:" >&2
compose -f "${COMPOSE_FILE}" logs --tail=120 backend >&2
exit 1
