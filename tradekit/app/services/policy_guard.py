from pathlib import Path
from typing import Any

import yaml

from app.models.proposal import PolicyViolation, TradeIntent, TradeProposalReview


class PolicyGuard:
    def __init__(self, policy: dict[str, Any]):
        self.policy = policy
        self.limits = policy.get("limits", {})

    @classmethod
    def from_file(cls, path: Path) -> "PolicyGuard":
        if not path.exists():
            return cls({})
        with path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        return cls(data)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.policy.get("mode", "read_only"),
            "default_profile": self.policy.get("default_profile", "demo"),
            "require_human_confirm": self.policy.get("require_human_confirm", True),
            "limits": self.limits,
            "allowed_modules": self.policy.get("allowed_modules", []),
        }

    def review(self, intent: TradeIntent) -> TradeProposalReview:
        violations: list[PolicyViolation] = []
        warnings: list[str] = []
        mode = self.policy.get("mode", "read_only")
        require_human_confirm = bool(self.policy.get("require_human_confirm", True))

        max_order_notional = float(self.limits.get("max_order_notional_usdt", 0) or 0)
        if max_order_notional and intent.notional_usdt > max_order_notional:
            violations.append(
                PolicyViolation(
                    code="MAX_ORDER_NOTIONAL",
                    message=f"单笔名义金额 {intent.notional_usdt} USDT 超过上限 {max_order_notional} USDT",
                )
            )

        max_leverage = float(self.limits.get("max_leverage", 0) or 0)
        if intent.leverage and max_leverage and intent.leverage > max_leverage:
            violations.append(
                PolicyViolation(
                    code="MAX_LEVERAGE",
                    message=f"杠杆 {intent.leverage}x 超过上限 {max_leverage}x",
                )
            )

        if mode == "read_only":
            violations.append(
                PolicyViolation(
                    code="READ_ONLY_MODE",
                    message="当前策略为只读模式，只允许生成交易建议草稿，不允许执行下单",
                )
            )

        if intent.reason.strip() == "":
            warnings.append("交易理由为空，建议补充触发信号、失效条件和止损计划。")

        approved = not violations and not require_human_confirm
        next_action = "draft_only"
        if not violations and require_human_confirm:
            next_action = "needs_human_confirm"
        elif approved:
            next_action = "eligible_for_execution_gateway"

        return TradeProposalReview(
            approved_for_execution=approved,
            mode=mode,
            require_human_confirm=require_human_confirm,
            intent=intent,
            violations=violations,
            warnings=warnings,
            next_action=next_action,
        )
