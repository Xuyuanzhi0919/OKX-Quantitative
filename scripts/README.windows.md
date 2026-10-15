# OKK Windows 本地开发

环境已配置：Node.js 22.23.3 / npm、Python 3.12.10、PostgreSQL 15.19、Memurai 4.0.5（Redis API 7.0.15）、OKX CLI 和 MCP。

在项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 stop
```

- 前端：http://127.0.0.1:5173
- 后端文档：http://127.0.0.1:8000/docs
- TradeKit：http://127.0.0.1:8010/ui/
- 本地管理员：`admin`；密码保存在项目根目录 `.env.local` 的 `DEV_ADMIN_PASSWORD`。
- 后端虚拟环境：`backend\.venv`；TradeKit：`tradekit\.venv`。
- 本地数据库：`okk_quant_dev`，角色 `okk_dev`，连接配置保存在 `.env.local`。
- 日志和应用进程记录：`.dev-windows\`。

独立工具安装在 `%LOCALAPPDATA%\Programs\OKKDev`；数据库数据位于 `%LOCALAPPDATA%\OKKDev`。用户 PATH 已更新，新终端可使用 node、npm、python、pip、psql 和 okx；已打开的终端需重新打开。

默认启动跳过后端 startup/shutdown 自动任务，因此不会自动恢复策略、连接交易所 WebSocket 或启动通知监控。API、数据库、前端和 TradeKit 可用于开发。需要启动完整后台任务时，先 stop，再执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 start -EnableBackgroundTasks
```

完整后台任务会读取现有 `backend\notification_config.json`，并恢复本地数据库中正在运行的策略。OKX 模拟盘默认开启，API 凭证为空，代理端口配置为本机 7897。OKX CLI 尚未配置账户凭证；需要账户查询时自行运行 `okx config init`。本次未执行交易、导入历史备份或修改现有 `backend\.env`。

当前项目 SQL 没有启用 TimescaleDB 超表，因此使用标准 PostgreSQL。TimescaleDB 扩展、Docker/WSL 和 Celery worker 尚未安装或启动。iOS 子项目需要 macOS/Xcode。Memurai Developer 仅用于开发测试，连续运行 10 天后需重新启动。
