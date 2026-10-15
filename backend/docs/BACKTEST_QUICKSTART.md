# 回测系统快速入门指南

## 好消息！

**回测系统已完全实现！** 包括：
- K线数据管理
- 回测引擎（事件驱动）
- 性能指标计算（夏普比率、最大回撤等）
- 网格策略回测
- 完整的REST API

## 快速开始（3步）

### 步骤1：下载历史K线数据

```bash
# 使用curl下载BTC-USDT的1小时K线数据（最近30天）
curl -X POST http://localhost:8000/api/v1/backtest/fetch-kline \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USDT",
    "interval": "1H",
    "start_time": 1727404800000,
    "end_time": 1730073600000
  }'
```

### 步骤2：运行网格策略回测

```bash
# 启动网格策略回测
curl -X POST http://localhost:8000/api/v1/backtest/run/grid \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USDT",
    "interval": "1H",
    "start_time": 1727404800000,
    "end_time": 1730073600000,
    "initial_capital": 10000,
    "params": {
      "grid_num": 20,
      "price_lower": 60000,
      "price_upper": 70000,
      "amount_per_grid": 500
    }
  }'
```

### 步骤3：查看回测结果

```bash
# 查询回测结果（使用返回的backtest_id）
curl http://localhost:8000/api/v1/backtest/results/{backtest_id}
```

## 完整API文档

访问Swagger文档查看所有API：
```
http://localhost:8000/docs#/Backtest
```

## 核心API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/backtest/fetch-kline` | 下载历史K线数据 |
| GET | `/api/v1/backtest/klines/{symbol}/{interval}` | 查询K线数据 |
| GET | `/api/v1/backtest/data-range` | 查看已有数据范围 |
| POST | `/api/v1/backtest/run/grid` | 运行网格策略回测 |
| GET | `/api/v1/backtest/results/{id}` | 获取回测结果 |
| GET | `/api/v1/backtest/list` | 查询回测历史列表 |

## 回测结果示例

```json
{
  "id": 1,
  "symbol": "BTC-USDT",
  "interval": "1H",
  "initial_capital": 10000,
  "final_capital": 11250,
  "total_return": 0.125,
  "annual_return": 0.487,
  "sharpe_ratio": 1.82,
  "max_drawdown": 0.086,
  "win_rate": 0.68,
  "total_trades": 47,
  "trades": [...],
  "equity_curve": [...]
}
```

## 性能指标说明

- **Total Return (总收益率)**: 总盈亏百分比
- **Annual Return (年化收益率)**: 按年化计算的收益率
- **Sharpe Ratio (夏普比率)**: 风险调整后收益，越高越好（>1.0较好，>2.0优秀）
- **Max Drawdown (最大回撤)**: 权益曲线最大跌幅，越小越好
- **Win Rate (胜率)**: 盈利交易占比
- **Total Trades (总交易数)**: 完成的交易次数

## 接口调用

启动后端后访问 `http://localhost:8000/docs`，在“回测系统”分组查看当前请求参数、认证要求和返回结构。独立示例脚本已清理。

## 前端界面（开发中）

回测系统前端界面正在开发中，即将上线：
- 可视化回测设置
- 交互式权益曲线图
- 交易明细表
- 性能指标仪表盘

## 高级功能

### 参数优化（即将推出）
- 网格搜索
- 遗传算法优化
- 参数敏感性分析

### 多策略支持
目前支持网格策略，后续将支持：
- 马丁格尔策略
- 均线策略
- 自定义策略

## 常见问题

**Q: 如何获取时间戳？**
```python
import time
from datetime import datetime, timedelta

# 30天前
start = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
# 现在
end = int(datetime.now().timestamp() * 1000)
```

**Q: 支持哪些K线周期？**
- 1m, 5m, 15m, 30m (分钟)
- 1H, 4H (小时)
- 1D (天)

**Q: 回测数据存储在哪里？**
- K线数据: PostgreSQL的`klines`表（TimescaleDB优化）
- 回测结果: PostgreSQL的`backtests`表

## 下一步

1. 尝试运行一个回测
2. 调整策略参数观察结果变化
3. 对比不同参数的性能指标
4. 找到最优参数后应用到实盘策略

## 技术架构

```
回测引擎 (BacktestEngine)
├── 数据层 (K线管理)
├── 策略层 (网格策略)
├── 执行层 (订单模拟)
└── 分析层 (性能指标)
```

## 贡献指南

想要添加新策略或改进回测引擎？查看：
- `backend/app/services/backtest/` - 回测核心代码
- `backend/docs/backtest_system_design.md` - 架构设计文档
