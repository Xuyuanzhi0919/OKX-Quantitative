#!/usr/bin/env bash
set -euo pipefail

# Build and push production Docker images.
#
# Example:
#   OKK_IMAGE_REPO=registry.cn-hangzhou.aliyuncs.com/your-ns/okk OKK_IMAGE_TAG=v1 ./scripts/docker-publish.sh
#
# This pushes:
#   registry.cn-hangzhou.aliyuncs.com/your-ns/okk-backend:v1
#   registry.cn-hangzhou.aliyuncs.com/your-ns/okk-frontend:v1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_REPO="${OKK_IMAGE_REPO:?请设置 OKK_IMAGE_REPO，例如 registry.cn-hangzhou.aliyuncs.com/your-ns/okk 或 ghcr.io/yourname/okk}"
IMAGE_TAG="${OKK_IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
BACKEND_IMAGE="${OKK_BACKEND_IMAGE:-${IMAGE_REPO}-backend:${IMAGE_TAG}}"
FRONTEND_IMAGE="${OKK_FRONTEND_IMAGE:-${IMAGE_REPO}-frontend:${IMAGE_TAG}}"
PLATFORMS="${OKK_PLATFORMS:-linux/amd64}"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

cd "${ROOT_DIR}"

echo "==> 构建镜像"
echo "backend:  ${BACKEND_IMAGE}"
echo "frontend: ${FRONTEND_IMAGE}"
echo "platform: ${PLATFORMS}"

export DOCKER_DEFAULT_PLATFORM="${PLATFORMS}"
export OKK_BACKEND_IMAGE="${BACKEND_IMAGE}"
export OKK_FRONTEND_IMAGE="${FRONTEND_IMAGE}"

compose -f docker-compose.prod.yml build backend frontend

echo "==> 推送镜像"
docker push "${BACKEND_IMAGE}"
docker push "${FRONTEND_IMAGE}"

echo ""
echo "发布完成。服务器 .env 可配置："
echo "OKK_BACKEND_IMAGE=${BACKEND_IMAGE}"
echo "OKK_FRONTEND_IMAGE=${FRONTEND_IMAGE}"
