from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models.proposal import TradeIntent, TradeProposalReview
from app.services.policy_guard import PolicyGuard

router = APIRouter()


@router.post("/review", response_model=TradeProposalReview)
async def review_proposal(
    intent: TradeIntent,
    settings: Settings = Depends(get_settings),
) -> TradeProposalReview:
    guard = PolicyGuard.from_file(settings.policy_file)
    return guard.review(intent)
