# OKK Status iOS 小组件

用于展示服务器上策略 1 的运行状态、累计盈亏、持仓数量、交易次数、胜率和最新信号。

## 生成工程

```bash
cd ios/OKKStatus
xcodegen generate
open OKKStatus.xcodeproj
```

在 Xcode 中为 `OKKStatus` 和 `OKKStatusWidget` 选择同一个开发团队，然后运行主应用。安装后长按 iPhone 主屏幕，点击 `+`，搜索“OKK 策略”。

## 修改服务器或策略

编辑 `Shared/StrategyAPI.swift`：

```swift
static let serverURL = URL(string: "http://43.155.213.45:8088")!
static let strategyID = 1
```

当前服务器使用 HTTP，因此 Info.plist 临时允许了非 HTTPS 请求。正式长期使用时应配置域名和 HTTPS，然后移除 `NSAllowsArbitraryLoads`。

