# OKK 量化交易系统

基于 OKX 的量化交易项目，包含 FastAPI 后端、React 管理界面、TradeKit 只读网关，以及 iOS 应用和小组件。支持模拟盘/实盘配置、策略管理、回测、风控监控和通知。项目仍在开发中。

## 当前功能

- OKX REST 接口、HMAC 签名和代理；行情、K 线、订单簿、余额、持仓和订单管理。
- 策略创建、启动、停止、事件记录、盈亏统计；启动时尝试恢复数据库中运行中的策略。
- Socket.IO 前端推送与 OKX WebSocket 行情、私有频道接入。
- K 线数据管理、回测任务、交易明细、绩效指标及独立研究脚本。
- 账户风险、山寨币动量、TradFi 异动监控；Telegram、Server酱、PushPlus、企业微信、Bark、Android 推送。
- 用户登录、JWT、服务访问令牌和移动端只读令牌。
- TradeKit 行情/余额查询、OKK 状态聚合、策略建议与交易意图评估；当前没有执行下单接口。
- iOS 策略状态、盈亏、信号、持仓详情和 WidgetKit 小组件。

### 可用策略

当前策略管理器 `create_strategy()` 注册四种策略：

| 类型 | 策略 |
| --- | --- |
| `adaptive_grid_trend` | 自适应趋势网格 |
| `arbitrage` | 现货－永续套利 |
| `top_gainers_momentum` | 涨幅榜前三 15m 动量 |
| `explosive_momentum_chaser` | 爆量急拉追涨 |

模型枚举保留的其他历史类型不代表当前引擎支持启动。通用回测支持 `adaptive_grid_trend`、`arbitrage`、`fixed_tp_sl`；涨幅榜动量使用独立分析接口。研究脚本位于 `backend/scripts/` 和 `tradekit/research/`。

## 技术栈与结构

- 后端：Python 3.11+、FastAPI、SQLAlchemy、Pydantic、Loguru。
- 数据：PostgreSQL 15、Redis 7；Docker 使用 TimescaleDB 镜像，当前 SQL 未创建超表，Windows 使用标准 PostgreSQL。
- 前端：React 18、TypeScript、Vite 5、Ant Design 5、Tailwind CSS、Zustand、TanStack Query、ECharts、Lightweight Charts。
- 实时通信：Socket.IO、OKX WebSocket。
- Celery / Flower 已列入依赖，开发启动脚本不启动 worker。
- iOS：SwiftUI、WidgetKit、iOS 17+、XcodeGen。

```text
OKK/
├── backend/
│   ├── app/api/          # API 路由
│   ├── app/core/         # 配置、数据库、认证
│   ├── app/models/       # 数据模型
│   ├── app/services/     # 策略、交易所、回测、监控和通知
│   ├── app/websocket/    # Socket.IO 和 OKX WebSocket
│   ├── migrations/      # SQL 增量迁移
│   ├── scripts/         # 回测、优化和研究
│   └── init_complete.sql
├── frontend/src/        # 管理界面
├── tradekit/            # 独立只读网关、UI 和研究
├── ios/OKKStatus/       # iOS 应用与小组件
├── scripts/             # 开发和部署工具
├── nginx/               # 反向代理
├── docker-compose.prod.yml
└── docker-compose.china.yml
```

## Windows 本地启动

适用于已安装 OKKDev 工具、创建根目录 `.env.local`、后端和 TradeKit 虚拟环境的电脑。此脚本是启动器，不是安装器；固定工具路径见 `scripts/windows-env.ps1`。

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 stop
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://127.0.0.1:5173 |
| API 文档 | http://127.0.0.1:8000/docs |
| 后端健康检查 | http://127.0.0.1:8000/health |
| TradeKit UI | http://127.0.0.1:8010/ui/ |

本地数据库为 `okk_quant_dev`；管理员 `admin` 的密码取自 `.env.local` 中的 `DEV_ADMIN_PASSWORD`。日志和进程记录位于 `.dev-windows/`。

默认跳过后端 startup/shutdown 自动任务，不恢复策略或启动交易所 WebSocket、通知和账户监控。需要完整任务时，先停止，再执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 start -EnableBackgroundTasks
```

完整启动会尝试恢复数据库中运行中的策略。详见 [Windows 开发说明](scripts/README.windows.md)。

## 手动安装与启动

准备 Git、Python（建议 3.11 或 3.12）、Node.js/npm、PostgreSQL 15、Redis 7。

```bash
git clone https://github.com/Xuyuanzhi0919/OKK.git
cd OKK
```

复制 `backend/.env.example` 为 `backend/.env`，修改数据库、Redis、`SECRET_KEY` 等配置，保留 `OKX_SIMULATED=true` 用于模拟盘测试。

### 数据库初始化

先创建与 `DATABASE_URL` 一致的数据库和用户。以下命令从项目根目录执行，**仅用于新数据库**：

```bash
psql -h localhost -U okk_user -d okk_quant -v ON_ERROR_STOP=1 -f backend/init_complete.sql
psql -h localhost -U okk_user -d okk_quant -v ON_ERROR_STOP=1 -f backend/migrations/011_add_adaptive_grid_trend_strategy.sql
psql -h localhost -U okk_user -d okk_quant -v ON_ERROR_STOP=1 -f backend/migrations/014_add_top_gainers_momentum_strategy.sql
psql -h localhost -U okk_user -d okk_quant -v ON_ERROR_STOP=1 -f backend/migrations/015_add_explosive_momentum_chaser_strategy.sql
```

初始化 SQL 包含 `admin / admin123` 种子账户，重复执行会覆盖该账户密码，上线前应更新密码。已有数据库应备份后按实际结构选择迁移，避免重跑初始化或批量执行全部迁移，尤其是重置管理员密码的 `010`。

### 后端

必须从 `backend/` 目录运行：

```bash
cd backend
python -m venv venv
source venv/bin/activate
# Windows PowerShell 改用：.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

也可用 `uvicorn app.main:socket_app --reload --host 127.0.0.1 --port 8000`。保留 `socket_app` 入口以启用 Socket.IO；标准启动会执行完整后台任务。

### 前端

新开终端，从项目根目录运行：

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 登录。API 前缀 `/api/v1`，文档 http://localhost:8000/docs 和 http://localhost:8000/redoc。

macOS/Linux 准备好 `backend/venv`、`tradekit/.venv`、前端依赖和数据库后，可用 `bash scripts/dev.sh start`，以及 `status`、`logs`、`stop`、`restart`。脚本启动后端、前端、TradeKit，不安装或启动 PostgreSQL/Redis。

## 配置说明

### OKX 与通知

- 在前端 API 配置页面添加 OKX 凭据并选择模拟盘或实盘；策略可绑定指定 API 配置。
- 后端也声明了 `OKX_API_KEY`、`OKX_SECRET_KEY`、`OKX_PASSPHRASE`、`OKX_SIMULATED` 环境配置；策略启动和恢复使用数据库中的 API 配置。
- 中国地区连接 OKX 通常需要代理，例如在 `backend/.env` 添加 `OKX_PROXY=http://127.0.0.1:7897`，按本机端口调整。容器内需使用容器可访问的代理地址。
- 通知和监控读取 `backend/notification_config.json`，参考 `backend/notification_config.example.json`。已有配置应合并所需字段，避免覆盖渠道凭据。
- API 密钥只授予查询和交易权限，禁止提现权限。不要提交 `.env`、通知令牌和 iOS 私密配置。

### 认证边界

前端使用 `/api/v1/auth/login` 返回的 JWT。`API_ACCESS_TOKEN` 为完整服务访问令牌；`MOBILE_READ_TOKEN` 用于指定移动端只读接口，应设置为独立随机值。

共享认证依赖为兼容旧版单用户看板，允许部分 GET 请求在缺少或无效令牌时回退到默认用户；移动端专用依赖要求有效令牌。前端登录页不等同于所有 API 均强制鉴权，公网部署需结合具体路由和反向代理限制访问。

### 前端网络

Vite 将 `/api` 转发到 `127.0.0.1:8000`，将 `/tradekit-api` 转发到 `127.0.0.1:8010`。部分请求使用 `VITE_API_BASE_URL`，默认开发地址为 `http://localhost:8000`；跨主机访问需核对 API 基址、CORS、WebSocket 地址。

## TradeKit 与 iOS

TradeKit 独立启动：

```bash
cd tradekit
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell 改用：.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

CLI 查询需要本机安装并配置 `okx`。桥接变量包括 `OKK_API_BASE_URL`、`OKK_API_TOKEN`、`OKK_USER_ID`，详见 [TradeKit 说明](tradekit/README.md)。当前主前端路由未挂载独立 TradeKit 页面，可直接访问网关 `/ui/`。

iOS 需要 macOS、Xcode、iOS 17+。复制 `Config/Secrets.xcconfig.example` 为 `Config/Secrets.xcconfig`，配置与后端一致的 `MOBILE_READ_TOKEN`，设置服务器地址和签名团队。移动端自动选择爆量追涨策略，详见 [iOS 配置说明](ios/OKKStatus/README.md)。

## Docker 部署

仓库提供 `docker-compose.prod.yml` 和 `docker-compose.china.yml`，没有默认的 `docker-compose.yml`。生产配置读取**根目录 `.env`**，不同于手动启动的 `backend/.env`。

部署前配置 `POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`SECRET_KEY`、`DEBUG=false`、`DOMAIN` 及后端其他必需配置；核对 Redis 认证健康检查、通知文件和代理地址，为已有数据库应用所需迁移。初始化 SQL 仅在数据库数据卷首次初始化时自动执行，新增策略枚举仍需按前文补齐。

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f backend
```

生产文件默认映射 Nginx `8088`、前端 `3000`、后端 `8000`、PostgreSQL `54321`、Redis `63791`。TradeKit 与 iOS 不包含在编排中。策略管理器为进程内单例，后端保持一个 worker，避免重复运行策略。

其他资料见 [1Panel 部署指南](1panel-deploy-guide.md)；部署脚本位于 `scripts/`，操作前以当前 Compose 和脚本为准。

## 开发与验证

新增策略需继承 `StrategyBase`，实现 `start()`、`on_tick()`、`on_kline()`、`on_order_update()`、`stop()`，在 `StrategyType`、管理器映射和数据库枚举中注册；回测引擎需另外注册。

API 路由在 `backend/app/api/__init__.py` 聚合，页面路由在 `frontend/src/App.tsx` 注册；日志统一使用 `from loguru import logger`。

```bash
# 从 backend 目录运行与修改相关的测试，例如
python -m pytest test_api_auth.py test_fixed_tp_sl_backtest.py

# 从 frontend 目录构建
npm run build
```

部分测试和研究脚本需要数据库、网络或历史行情，运行前检查各自依赖。

最后更新：2026-10-15
