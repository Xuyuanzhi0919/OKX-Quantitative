import asyncio
from typing import Any

from app.services.okk_client import OKKClient
from app.services.position_attribution_store import PositionAttributionStore


class StrategyBridge:
    def __init__(self, client: OKKClient, attribution_store: PositionAttributionStore | None = None):
        self.client = client
        self.attribution_store = attribution_store

    async def status(self) -> dict[str, Any]:
        health = await self.client.get_health()
        return {
            "connected": not self._is_error(health),
            "health": health,
            "base_url": self.client.base_url,
            "user_id": self.client.user_id,
        }

    async def overview(self) -> dict[str, Any]:
        strategies, balance, positions = await asyncio.gather(
            self.client.list_strategies(),
            self.client.get_balance(),
            self.client.list_positions("SWAP"),
        )
        strategy_items = self._extract_strategy_items(strategies)
        active_positions = self._attach_attributions(positions if isinstance(positions, list) else [])

        return {
            "status": await self.status(),
            "strategy_count": len(strategy_items),
            "running_strategy_count": len([s for s in strategy_items if self._norm(s.get("status")) == "running"]),
            "strategies": strategy_items,
            "balance": balance,
            "swap_positions": active_positions,
            "health_report": self._build_health_report(strategy_items, active_positions, balance),
            "copilot_notes": self._overview_notes(strategy_items, active_positions, balance),
        }

    async def strategy_advice(self, strategy_id: int) -> dict[str, Any]:
        strategy, stats, risk, positions = await asyncio.gather(
            self.client.get_strategy(strategy_id),
            self.client.get_strategy_stats(strategy_id),
            self.client.get_strategy_risk(strategy_id),
            self.client.list_positions("SWAP"),
        )
        active_positions = self._attach_attributions(positions if isinstance(positions, list) else [])
        advice = self._build_strategy_advice(strategy, stats, risk, active_positions)
        return {
            "strategy_id": strategy_id,
            "strategy": strategy,
            "stats": stats,
            "risk": risk,
            "related_positions": self._positions_for_strategy_symbol(strategy, active_positions),
            "advice": advice,
        }

    def _overview_notes(self, strategies: list[dict[str, Any]], positions: list[dict[str, Any]], balance: Any) -> list[str]:
        notes: list[str] = []
        report = self._build_health_report(strategies, positions, balance)
        running = [s for s in strategies if self._norm(s.get("status")) == "running"]
        if not strategies:
            notes.append("未读取到 OKK 策略，先确认主后端是否已启动或数据库是否有策略。")
        elif not running:
            notes.append("当前没有运行中的策略，适合先做参数复盘或模拟盘预检。")
        else:
            notes.append(f"当前有 {len(running)} 个运行中策略，建议优先检查持仓、风控和未成交订单。")

        if positions:
            total_notional = sum(self._float(p.get("notional_usd") or p.get("notionalUsd")) for p in positions)
            notes.append(f"读取到 {len(positions)} 个 SWAP 持仓，名义价值约 {total_notional:.2f} USD。")
        else:
            notes.append("未读取到 SWAP 活跃持仓。")

        if self._is_error(balance):
            notes.append("余额接口不可用，建议先检查 OKK API 配置或 OKX 代理。")
        if report["unresolved_orphan_position_count"]:
            notes.append(f"检测到 {report['unresolved_orphan_position_count']} 个未归因的 SWAP 持仓，建议先确认是否为手动仓位。")
        elif report["manual_position_count"]:
            notes.append(f"已确认 {report['manual_position_count']} 个手动仓位，副驾驶会继续纳入账户级风险计算。")
        if report["risk_level"] != "low":
            notes.append(report["summary"])
        return notes

    def _build_health_report(
        self,
        strategies: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        balance: Any,
    ) -> dict[str, Any]:
        total_equity = self._extract_total_equity(balance)
        position_notional = sum(self._float(p.get("notional_usd") or p.get("notionalUsd")) for p in positions)
        unrealized_pnl = sum(self._float(p.get("unrealized_pnl") or p.get("upl")) for p in positions)
        orphan_positions = [
            p for p in positions
            if not p.get("strategy_id") and not p.get("strategy_name")
        ]
        unresolved_orphan_positions = [
            p for p in orphan_positions
            if (p.get("attribution") or {}).get("kind") not in ("manual", "strategy", "ignored")
        ]
        manual_positions = [
            p for p in positions
            if (p.get("attribution") or {}).get("kind") == "manual"
        ]
        strategy_symbols = {
            item.get("symbol")
            for item in strategies
            if item.get("symbol")
        }
        unmatched_positions = [
            p for p in positions
            if (p.get("symbol") or p.get("inst_id") or p.get("instId")) not in strategy_symbols
        ]

        notional_to_equity = position_notional / total_equity if total_equity > 0 else 0.0
        pnl_to_equity = unrealized_pnl / total_equity if total_equity > 0 else 0.0
        max_leverage = max([self._float(p.get("leverage") or p.get("lever")) for p in positions] or [0.0])
        min_margin_ratio = min([
            self._float(p.get("mgn_ratio") or p.get("mgnRatio"))
            for p in positions
            if self._float(p.get("mgn_ratio") or p.get("mgnRatio")) > 0
        ] or [0.0])

        risk_level = "low"
        checks: list[dict[str, Any]] = []
        actions: list[str] = []

        def add_check(code: str, level: str, message: str) -> None:
            checks.append({"code": code, "level": level, "message": message})

        if self._is_error(balance):
            risk_level = "high"
            add_check("BALANCE_UNAVAILABLE", "high", "余额接口不可用，无法判断账户风险。")
            actions.append("先修复 OKK API 配置或 OKX 网络代理。")
        elif total_equity <= 0:
            risk_level = "medium"
            add_check("EMPTY_EQUITY", "medium", "账户净值读取为 0，建议确认账户类型和 API 权限。")

        if not strategies and unresolved_orphan_positions:
            risk_level = "high"
            add_check("POSITIONS_WITHOUT_STRATEGY", "high", "存在未归因持仓但 OKK 没有策略记录，可能是手动仓位或孤儿仓位。")
            actions.append("先给持仓做归因，不建议新增自动策略仓位。")

        if unresolved_orphan_positions:
            risk_level = "high" if risk_level != "high" and position_notional > total_equity else risk_level
            add_check("ORPHAN_POSITIONS", "medium", f"检测到 {len(unresolved_orphan_positions)} 个未归因的未绑定策略持仓。")
            actions.append("把未绑定持仓标记为手动仓位、策略仓位或忽略。")

        if manual_positions:
            add_check("MANUAL_POSITIONS_ACKNOWLEDGED", "low", f"已确认 {len(manual_positions)} 个手动仓位，仍需纳入账户级风险计算。")

        if notional_to_equity >= 3:
            risk_level = "high"
            add_check("HIGH_NOTIONAL_EXPOSURE", "high", f"持仓名义价值约为净值的 {notional_to_equity:.2f} 倍。")
            actions.append("暂停新增仓位，优先降低杠杆或减仓。")
        elif notional_to_equity >= 1:
            risk_level = "medium" if risk_level == "low" else risk_level
            add_check("MEDIUM_NOTIONAL_EXPOSURE", "medium", f"持仓名义价值约为净值的 {notional_to_equity:.2f} 倍。")

        if pnl_to_equity <= -0.05:
            risk_level = "high"
            add_check("UNREALIZED_LOSS", "high", f"未实现亏损约为净值的 {pnl_to_equity:.2%}。")
            actions.append("检查止损和强平距离，不建议加仓摊平。")

        if max_leverage > 3:
            risk_level = "medium" if risk_level == "low" else risk_level
            add_check("LEVERAGE_ABOVE_POLICY", "medium", f"检测到最高杠杆 {max_leverage:.1f}x，高于 TradeKit 默认 3x。")

        if min_margin_ratio and min_margin_ratio < 2:
            risk_level = "high"
            add_check("LOW_MARGIN_RATIO", "high", f"最低保证金安全倍数约 {min_margin_ratio:.2f}。")
            actions.append("优先处理保证金风险。")

        if not checks:
            add_check("NO_MAJOR_RISK", "low", "未发现明显账户级风险。")
            actions.append("保持只读观察，等待策略信号或人工复盘。")

        summary = {
            "high": "账户存在高优先级风险，先处理持仓/风控，再考虑新增动作。",
            "medium": "账户有需要关注的风险项，建议只读观察或降低仓位。",
            "low": "当前账户级风险较低，可以继续观察策略信号。",
        }[risk_level]

        return {
            "risk_level": risk_level,
            "summary": summary,
            "total_equity": total_equity,
            "position_notional": position_notional,
            "notional_to_equity": notional_to_equity,
            "unrealized_pnl": unrealized_pnl,
            "pnl_to_equity": pnl_to_equity,
            "max_leverage": max_leverage,
            "min_margin_ratio": min_margin_ratio,
            "orphan_position_count": len(orphan_positions),
            "unresolved_orphan_position_count": len(unresolved_orphan_positions),
            "manual_position_count": len(manual_positions),
            "unmatched_position_count": len(unmatched_positions),
            "checks": checks,
            "suggested_actions": list(dict.fromkeys(actions)),
        }

    def _attach_attributions(self, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.attribution_store or not positions:
            return positions

        result: list[dict[str, Any]] = []
        keys = [self._position_key(pos) for pos in positions]
        attributions = self.attribution_store.get_many(keys)
        for pos, key in zip(positions, keys):
            item = dict(pos)
            item["position_key"] = key
            item["attribution"] = attributions.get(key)
            result.append(item)
        return result

    def _position_key(self, position: dict[str, Any]) -> str:
        pos_id = position.get("pos_id") or position.get("posId") or position.get("id")
        symbol = position.get("symbol") or position.get("inst_id") or position.get("instId") or "unknown"
        side = position.get("side") or position.get("pos_side") or position.get("posSide") or "net"
        if pos_id:
            return f"pos:{pos_id}"
        return f"symbol:{symbol}:{side}"

    def _build_strategy_advice(
        self,
        strategy: Any,
        stats: Any,
        risk: Any,
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        notes: list[str] = []
        actions: list[dict[str, str]] = []
        confidence = "medium"

        if self._is_error(strategy):
            return {
                "level": "blocked",
                "confidence": "low",
                "summary": "无法读取策略详情，先修复 OKK 主服务或策略 ID。",
                "notes": [str(strategy.get("error", strategy)) if isinstance(strategy, dict) else "strategy read failed"],
                "suggested_actions": [],
            }

        strategy_type = self._norm(strategy.get("type"))
        status = self._norm(strategy.get("status"))
        symbol = strategy.get("symbol") or ""
        related_positions = self._positions_for_strategy_symbol(strategy, positions)

        if self._is_error(stats):
            notes.append("策略统计接口不可用，建议不要仅凭当前建议调整实盘。")
            confidence = "low"
        else:
            total_profit = self._float(stats.get("total_profit") or stats.get("total_pnl"))
            win_rate = self._float(stats.get("win_rate"))
            if total_profit < 0:
                notes.append(f"策略累计收益为负：{total_profit:.2f}，建议检查止损和入场过滤。")
                actions.append({"type": "review", "message": "复盘最近成交，确认亏损来自震荡误触发还是趋势反转。"})
            if win_rate and win_rate < 40:
                notes.append(f"胜率偏低：{win_rate:.1f}%，建议降低仓位或提高信号确认门槛。")

        if isinstance(risk, dict) and risk.get("has_risk"):
            count = risk.get("triggered_count", 0)
            notes.append(f"OKK 风控已触发 {count} 条规则，应先处理风控再考虑加仓。")
            actions.append({"type": "risk", "message": "暂停新增交易，检查触发的风控规则。"})
            confidence = "high"
        elif self._is_error(risk):
            notes.append("风控接口不可用，建议保持只读观察。")
            confidence = "low"

        if status != "running":
            notes.append("策略当前未运行，建议先做 start-preflight 或回测复核。")
            actions.append({"type": "preflight", "message": "调用 OKK 策略启动预检，确认余额、仓位模式、杠杆和已有持仓。"})
        elif not related_positions:
            notes.append("策略运行中但未匹配到同交易对持仓，可能正在等待信号或刚完成平仓。")

        if strategy_type == "top_gainers_momentum":
            notes.append("涨幅榜动量策略波动极高，建议限制单笔风险并确认 5m/15m 动量没有过热追高。")
            actions.append({"type": "guardrail", "message": "保持小仓位，优先模拟盘或只读观察候选币变化。"})
        elif strategy_type == "adaptive_grid_trend":
            notes.append("自适应趋势网格更适合主流币稳健参数，重点检查 ATR、最大仓位和杠杆是否一致。")
            actions.append({"type": "parameter_review", "message": "确认 live/backtest/frontend 参数均来自统一归一化配置。"})

        if symbol:
            actions.append({"type": "market_check", "message": f"用 TradeKit 查询 {symbol} 行情、资金费率和盘口后再决定是否调整。"})

        level = "observe"
        if any(item["type"] == "risk" for item in actions):
            level = "risk_first"
        elif status != "running":
            level = "preflight"

        return {
            "level": level,
            "confidence": confidence,
            "summary": self._summary_for_level(level),
            "notes": notes,
            "suggested_actions": actions,
            "execution_allowed": False,
            "execution_note": "TradeKit Gateway 当前只生成建议，不直接执行 OKK 策略启动、停止或下单。",
        }

    def _positions_for_strategy_symbol(self, strategy: Any, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(strategy, dict):
            return []
        symbol = strategy.get("symbol")
        if not symbol:
            return []
        return [p for p in positions if p.get("symbol") == symbol or p.get("inst_id") == symbol or p.get("instId") == symbol]

    def _extract_strategy_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("strategies", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    def _is_error(self, payload: Any) -> bool:
        return isinstance(payload, dict) and payload.get("ok") is False

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _extract_total_equity(self, balance: Any) -> float:
        if not isinstance(balance, dict):
            return 0.0
        payload = balance.get("data", balance)
        return self._float(payload.get("totalEq") or payload.get("total_equity"))

    def _norm(self, value: Any) -> str:
        if hasattr(value, "value"):
            value = value.value
        return str(value or "").lower()

    def _summary_for_level(self, level: str) -> str:
        if level == "risk_first":
            return "先处理风控，再考虑任何新增动作。"
        if level == "preflight":
            return "策略未运行，先做预检和参数复核。"
        return "保持观察，结合持仓、行情和策略统计决定是否调整。"
