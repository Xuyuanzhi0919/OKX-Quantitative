#!/bin/bash

# OKK量化交易系统部署脚本
# 适用于1Panel环境

set -e

echo "🚀 开始部署OKK量化交易系统..."

# 检查必要文件
if [ ! -f ".env.prod" ]; then
    echo "❌ 错误: .env.prod 文件不存在，请先配置环境变量"
    exit 1
fi

# 创建必要目录
echo "📁 创建必要目录..."
mkdir -p nginx/logs
mkdir -p backend/logs

# 设置权限
chmod +x deploy.sh

# 停止现有容器
echo "🛑 停止现有容器..."
docker-compose -f docker-compose.prod.yml down || true

# 清理旧镜像 (可选)
read -p "是否清理旧的Docker镜像? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🧹 清理旧镜像..."
    docker system prune -f
fi

# 构建并启动服务
echo "🔨 构建并启动服务..."
docker-compose -f docker-compose.prod.yml up -d --build

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 30

# 检查服务状态
echo "🔍 检查服务状态..."
docker-compose -f docker-compose.prod.yml ps

# 检查健康状态
echo "🏥 检查服务健康状态..."
for i in {1..10}; do
    if curl -f http://localhost:8000/ > /dev/null 2>&1; then
        echo "✅ 后端服务启动成功"
        break
    fi
    if [ $i -eq 10 ]; then
        echo "❌ 后端服务启动失败"
        docker-compose -f docker-compose.prod.yml logs backend
        exit 1
    fi
    echo "等待后端服务启动... ($i/10)"
    sleep 10
done

# 显示部署信息
echo ""
echo "🎉 部署完成!"
echo ""
echo "📋 服务信息:"
echo "  - Nginx入口: http://localhost:8088 (请配置1Panel反向代理指向此端口)"
echo "  - 前端内部: http://localhost:3000"
echo "  - 后端API: http://localhost:8000"
echo "  - API文档: http://localhost:8088/api/docs"
echo "  - 数据库: localhost:5432"
echo "  - Redis: localhost:6379"
echo ""
echo "📝 下一步操作:"
echo "  1. 在1Panel中创建反向代理网站"
echo "  2. 代理地址填写: http://127.0.0.1:8088"
echo "  3. 配置SSL证书 (在1Panel中)"
echo "  4. 配置OKX API密钥"
echo ""
echo "📊 查看日志命令:"
echo "  docker-compose -f docker-compose.prod.yml logs -f [service_name]"
echo ""
echo "🔧 管理命令:"
echo "  启动: docker-compose -f docker-compose.prod.yml up -d"
echo "  停止: docker-compose -f docker-compose.prod.yml down"
echo "  重启: docker-compose -f docker-compose.prod.yml restart"