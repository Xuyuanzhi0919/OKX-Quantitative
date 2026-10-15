# OKK Status iOS 应用与小组件

基于 SwiftUI 和 WidgetKit，展示策略运行状态、账户与策略持仓数、累计盈亏、交易次数、胜率、最新信号及持仓详情。需要 macOS、Xcode 和 iOS 17+；重新生成工程时需要 XcodeGen。

## 配置与运行

从项目根目录进入子项目：

```bash
cd ios/OKKStatus
cp Config/Secrets.xcconfig.example Config/Secrets.xcconfig
```

编辑 `Config/Secrets.xcconfig`，将 `MOBILE_READ_TOKEN` 设置为与后端一致的独立只读令牌，不要提交真实令牌。主应用与 Widget 均通过构建配置将该值写入各自的 `MobileReadToken` 属性。

在 `Shared/StrategyAPI.swift` 的 `OKKConfiguration.serverURL` 中设置自己的后端地址，然后打开现有工程：

```bash
open OKKStatus.xcodeproj
```

如修改了 `project.yml`，先运行 `xcodegen generate`。在 Xcode 中为 `OKKStatus` 和 `OKKStatusWidget` 设置同一个开发团队，再运行主应用。安装后长按 iPhone 主屏幕，添加“OKK 策略”小组件。

## 策略选择与认证

客户端请求 `GET /api/v1/strategies/mobile/current-snapshot`，使用 Bearer 只读令牌。无需在 Swift 中指定策略 ID：后端选择该用户的 `explosive_momentum_chaser` 策略，优先运行中的最新策略，否则选择最新记录。没有此类策略时需先在主系统创建。

移动端只读令牌对应后端默认用户；如使用其他用户的 JWT，策略选择按该用户进行。缺少或无效令牌会导致请求失败。

## 网络

当前工程允许 HTTP 请求。部署时应配置自己的服务器地址和 HTTPS，并在不再需要明文 HTTP 时移除 `NSAllowsArbitraryLoads`。真机需要能够访问后端，不能使用指向手机自身的 `localhost`。
