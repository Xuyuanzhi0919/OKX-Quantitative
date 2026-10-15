# OKK量化交易系统 - API接口文档

## 📋 目录

- [公共数据接口](#公共数据接口) - 无需认证
- [账户持仓接口](#账户持仓接口) - 需要认证
- [交易订单接口](#交易订单接口) - 需要认证

---

## 🌐 公共数据接口

### 1. 获取实时行情

**接口**: `GET /api/v1/market/ticker/{symbol}`

**说明**: 获取单个产品的实时行情信息

**请求参数**:
- `symbol` (路径参数): 产品ID,如 BTC-USDT, BTC-USD-SWAP

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "last": "56956.1",
    "lastSz": "3",
    "askPx": "56959.1",
    "askSz": "10582",
    "bidPx": "56959",
    "bidSz": "4552",
    "open24h": "55926",
    "high24h": "57641.1",
    "low24h": "54570.1",
    "volCcy24h": "81137.755",
    "vol24h": "46258703",
    "ts": "1620289117764"
  }
}
```

---

### 2. 获取K线数据

**接口**: `GET /api/v1/market/kline/{symbol}`

**说明**: 获取指定产品的K线数据

**请求参数**:
- `symbol` (路径参数): 产品ID
- `timeframe` (查询参数,可选): 时间粒度,默认1m
  - 支持: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 1D, 1W等
- `limit` (查询参数,可选): 返回数量,最大300,默认100
- `after` (查询参数,可选): 请求此时间戳之前的数据
- `before` (查询参数,可选): 请求此时间戳之后的数据

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "ts": "1597026383085",
      "o": "3.721",
      "h": "3.743",
      "l": "3.677",
      "c": "3.708",
      "vol": "8422410",
      "volCcy": "22698348.04",
      "volCcyQuote": "12698348.04",
      "confirm": "0"
    }
  ]
}
```

---

### 3. 获取订单簿深度

**接口**: `GET /api/v1/market/orderbook/{symbol}`

**说明**: 获取产品的订单簿深度数据

**请求参数**:
- `symbol` (路径参数): 产品ID
- `depth` (查询参数,可选): 深度档位,最大400,默认20

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "asks": [
      ["41006.8", "0.60038921", "0", "1"],
      ["41007.0", "0.50000000", "0", "2"]
    ],
    "bids": [
      ["41006.3", "0.30178218", "0", "2"],
      ["41006.0", "0.40000000", "0", "1"]
    ],
    "ts": "1629966436396"
  }
}
```

---

## 💼 账户持仓接口

### 4. 获取账户余额

**接口**: `GET /api/v1/positions/balance`

**说明**: 获取账户资产余额信息

**认证**: 需要配置OKX API密钥

**请求参数**:
- `ccy` (查询参数,可选): 币种,如 BTC,ETH。支持多个,逗号分隔

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "uTime": "1705474164160",
    "totalEq": "55837.43556134779",
    "availEq": "50000.00",
    "details": [
      {
        "ccy": "USDT",
        "eq": "4992.890093622894",
        "cashBal": "4850.435693622894",
        "availBal": "4834.317093622894",
        "frozenBal": "158.573",
        "upl": "-7.545600000000006"
      }
    ]
  }
}
```

---

### 5. 获取持仓列表

**接口**: `GET /api/v1/positions/list`

**说明**: 获取当前账户的持仓信息

**认证**: 需要配置OKX API密钥

**请求参数**:
- `inst_type` (查询参数,可选): 产品类型
  - MARGIN: 币币杠杆
  - SWAP: 永续合约
  - FUTURES: 交割合约
  - OPTION: 期权
- `inst_id` (查询参数,可选): 产品ID,支持多个,逗号分隔
- `pos_id` (查询参数,可选): 持仓ID,支持多个,逗号分隔

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "instId": "BTC-USDT",
      "instType": "MARGIN",
      "mgnMode": "isolated",
      "posId": "1752810569801498626",
      "posSide": "net",
      "pos": "0.00190433573",
      "availPos": "0.00190433573",
      "avgPx": "62961.4",
      "upl": "-0.0000033452492717",
      "uplRatio": "-0.0105311101755551",
      "lever": "5",
      "markPx": "62891.9"
    }
  ]
}
```

---

## 💹 交易订单接口

### 6. 创建订单

**接口**: `POST /api/v1/orders/create`

**说明**: 创建新的交易订单

**认证**: 需要配置OKX API密钥

**请求体**:
```json
{
  "symbol": "BTC-USDT",
  "side": "buy",
  "order_type": "limit",
  "amount": 0.001,
  "price": 50000,
  "td_mode": "cash",
  "cl_ord_id": "my_order_001"
}
```

**参数说明**:
- `symbol` (必填): 产品ID
- `side` (必填): 订单方向,buy/sell
- `order_type` (必填): 订单类型
  - market: 市价单
  - limit: 限价单
  - post_only: 只做maker单
  - fok: 全部成交或立即取消
  - ioc: 立即成交并取消剩余
- `amount` (必填): 委托数量
- `price` (可选): 委托价格,限价单必填
- `td_mode` (可选): 交易模式,默认cash
  - cash: 非保证金(现货)
  - isolated: 逐仓
  - cross: 全仓
- `cl_ord_id` (可选): 客户自定义订单ID
- `pos_side` (可选): 持仓方向,long/short/net
- `reduce_only` (可选): 是否只减仓,默认false
- `tgt_ccy` (可选): 市价单数量单位,base_ccy/quote_ccy

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "ordId": "12345689",
    "clOrdId": "my_order_001",
    "tag": "",
    "ts": "1695190491421",
    "sCode": "0",
    "sMsg": ""
  }
}
```

---

### 7. 取消订单

**接口**: `POST /api/v1/orders/cancel`

**说明**: 取消未完成的订单

**认证**: 需要配置OKX API密钥

**请求体**:
```json
{
  "symbol": "BTC-USDT",
  "order_id": "12345689"
}
```

**参数说明**:
- `symbol` (必填): 产品ID
- `order_id` (可选): 订单ID
- `cl_ord_id` (可选): 客户自定义订单ID
- 注: order_id和cl_ord_id至少传一个

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "ordId": "12345689",
    "clOrdId": "my_order_001",
    "ts": "1695190491421",
    "sCode": "0",
    "sMsg": ""
  }
}
```

---

### 8. 查询订单详情

**接口**: `POST /api/v1/orders/detail`

**说明**: 查询订单的详细信息

**认证**: 需要配置OKX API密钥

**请求体**:
```json
{
  "symbol": "BTC-USDT",
  "order_id": "12345689"
}
```

**参数说明**:
- `symbol` (必填): 产品ID
- `order_id` (可选): 订单ID
- `cl_ord_id` (可选): 客户自定义订单ID
- 注: order_id和cl_ord_id至少传一个

**响应示例**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "ordId": "680800019749904384",
    "clOrdId": "",
    "px": "50000",
    "sz": "0.001",
    "ordType": "limit",
    "side": "buy",
    "posSide": "net",
    "tdMode": "cash",
    "accFillSz": "0.001",
    "fillPx": "50100",
    "avgPx": "50100",
    "state": "filled",
    "fee": "-0.00000001",
    "feeCcy": "BTC",
    "cTime": "1708587373361",
    "uTime": "1708587373362"
  }
}
```

**订单状态说明**:
- `canceled`: 撤单成功
- `live`: 等待成交
- `partially_filled`: 部分成交
- `filled`: 完全成交
- `mmp_canceled`: 做市商保护机制导致的自动撤单

---

## ⚙️ 配置说明

### 环境变量配置

在 `.env` 文件中配置以下参数:

```env
# OKX API配置
OKX_API_KEY=your_api_key_here
OKX_SECRET_KEY=your_secret_key_here
OKX_PASSPHRASE=your_passphrase_here
OKX_SIMULATED=true  # true=模拟盘, false=实盘
```

### API密钥获取

1. 登录OKX交易所
2. 进入 账户设置 → API管理
3. 创建新的API密钥
4. 保存API Key、Secret Key和Passphrase
5. 设置IP白名单(推荐)
6. 设置权限: 读取、交易

⚠️ **安全提示**:
- 建议先使用模拟盘测试
- 不要将API密钥提交到代码仓库
- 定期更换API密钥
- 设置IP白名单限制访问

---

## 接口验证

启动后端后检查健康状态：

```bash
curl http://localhost:8000/health
```

访问 `http://localhost:8000/docs` 查看当前接口、认证要求和在线调用表单。公共行情、账户查询和交易接口的权限要求以具体路由为准；交易验证应使用模拟盘。

---

## 📝 错误码说明

| code | msg | 说明 |
|------|-----|------|
| 0 | success | 成功 |
| 400 | Bad Request | 请求参数错误 |
| 500 | Internal Server Error | 服务器内部错误 |

OKX API特定错误码请参考: https://www.okx.com/docs-v5/zh/#error-code

---

## 🔗 相关链接

- [OKX API官方文档](https://www.okx.com/docs-v5/zh/)
- [FastAPI文档](https://fastapi.tiangolo.com/)
- [项目GitHub仓库](#)

---

**最后更新**: 2025-01-24
