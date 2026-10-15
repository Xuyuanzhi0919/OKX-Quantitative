# OKK TradeKit Gateway

独立于 OKK 主交易系统的 AI TradeKit 网关。第一版只做只读能力和交易建议草稿，不直接实盘下单。

## 目标

- 调用官方 `okx` CLI / Agent Trade Kit 能力，而不把 OKX API Key 复制进 OKK 数据库。
- 为 Codex、OpenClaw、Claude、Cursor 或 OKK 主系统提供一个统一的本地交易工具层。
- 默认只读、默认模拟盘优先、默认不执行真实订单。

## 安装依赖

```bash
cd tradekit
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

安装 OKX Agent Trade Kit：

```bash
npm install -g @okx_ai/okx-trade-mcp @okx_ai/okx-trade-cli
okx config init
```

## 启动

```bash
cd tradekit
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

## 第一版接口

- `GET /health`：服务和本机 `okx` CLI 检测
- `GET /market/ticker/{inst_id}`：只读行情
- `GET /portfolio/balance`：账户余额只读查询
- `POST /proposal/review`：交易意图风控评估，只返回草稿，不下单
- `GET /okk/status`：检查 OKK 主后端连接
- `GET /okk/overview`：聚合 OKK 策略、余额和 SWAP 持仓
- `GET /okk/strategies/{strategy_id}/advice`：生成单策略副驾驶建议

## OKK 桥接配置

默认连接本机 OKK 后端：

```bash
OKK_API_BASE_URL=http://127.0.0.1:8000/api/v1
OKK_USER_ID=1
```

如果 OKK 后端配置了 `API_ACCESS_TOKEN`，可以加：

```bash
OKK_API_TOKEN=your_service_token
```

## 安全边界

- 本服务不读取、不展示 OKX API 密钥。
- API Key 仍由官方 `okx config init` 写入 `~/.okx/config.toml`。
- 当前版本没有执行下单接口。
- 后续如加入执行，必须经过 `policy_guard` 二次校验和人工确认。
