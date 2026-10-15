#!/usr/bin/env bash
set -euo pipefail

# Local one-command deploy:
#   OKK_DEPLOY_HOST=1.2.3.4 OKK_DEPLOY_USER=root OKK_DEPLOY_PATH=/opt/1panel/apps/okk-trading ./scripts/deploy-upload.sh
#
# Optional:
#   OKK_DEPLOY_PORT=22
#   OKK_MIGRATIONS="backend/migrations/012_add_strategy_api_config_binding.sql"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${OKK_DEPLOY_HOST:?请设置 OKK_DEPLOY_HOST，例如 1.2.3.4}"
DEPLOY_USER="${OKK_DEPLOY_USER:-root}"
DEPLOY_PORT="${OKK_DEPLOY_PORT:-22}"
DEPLOY_PATH="${OKK_DEPLOY_PATH:?请设置 OKK_DEPLOY_PATH，例如 /opt/1panel/apps/okk-trading}"
REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="okk_release_${STAMP}.tar.gz"
LOCAL_ARCHIVE="/tmp/${ARCHIVE_NAME}"
REMOTE_ARCHIVE="/tmp/${ARCHIVE_NAME}"
REMOTE_SCRIPT="/tmp/okk_server_update_${STAMP}.sh"

cleanup() {
  rm -f "${LOCAL_ARCHIVE}"
}
trap cleanup EXIT

echo "==> 打包本地代码: ${LOCAL_ARCHIVE}"
cd "${ROOT_DIR}"
tar -czf "${LOCAL_ARCHIVE}" \
  --exclude='.git' \
  --exclude='.idea' \
  --exclude='.DS_Store' \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='.env.prod' \
  --exclude='backend/.env' \
  --exclude='backend/venv' \
  --exclude='backend/venv-*' \
  --exclude='backend/__pycache__' \
  --exclude='backend/logs' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='nginx/logs' \
  .

echo "==> 上传代码包到服务器: ${REMOTE}:${REMOTE_ARCHIVE}"
scp -P "${DEPLOY_PORT}" "${LOCAL_ARCHIVE}" "${REMOTE}:${REMOTE_ARCHIVE}"

echo "==> 上传服务器更新脚本"
scp -P "${DEPLOY_PORT}" "${ROOT_DIR}/scripts/server-update-from-upload.sh" "${REMOTE}:${REMOTE_SCRIPT}"

echo "==> 远程执行 Docker 更新"
ssh -p "${DEPLOY_PORT}" "${REMOTE}" \
  "chmod +x '${REMOTE_SCRIPT}' && OKK_MIGRATIONS='${OKK_MIGRATIONS:-backend/migrations/012_add_strategy_api_config_binding.sql}' '${REMOTE_SCRIPT}' '${DEPLOY_PATH}' '${REMOTE_ARCHIVE}'"

echo "==> 发布完成"
