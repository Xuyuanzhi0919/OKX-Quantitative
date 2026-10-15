from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class TradeSide(str, Enum):
    buy = "buy"
    sell = "sell"
    long = "long"
    short = "short"
    close = "close"


class TradeIntent(BaseModel):
    inst_id: str = Field(..., examples=["BTC-USDT-SWAP"])
    side: TradeSide
    product_type: Literal["spot", "swap", "futures", "option"] = "swap"
    notional_usdt: float = Field(..., gt=0)
    leverage: float | None = Field(default=None, gt=0)
    order_type: Literal["market", "limit", "algo"] = "market"
    reason: str = Field(default="")
    source: str = Field(default="manual")


class PolicyViolation(BaseModel):
    code: str
    message: str


class TradeProposalReview(BaseModel):
    approved_for_execution: bool
    mode: str
    require_human_confirm: bool
    intent: TradeIntent
    violations: list[PolicyViolation]
    warnings: list[str]
    next_action: str

