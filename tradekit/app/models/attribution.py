from typing import Literal

from pydantic import BaseModel, Field


AttributionKind = Literal["manual", "strategy", "pending", "ignored"]


class PositionAttributionUpdate(BaseModel):
    kind: AttributionKind = Field(..., description="manual/strategy/pending/ignored")
    note: str = ""
    strategy_id: int | None = None
