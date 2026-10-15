from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models.attribution import PositionAttributionUpdate
from app.services.okk_client import OKKClient
from app.services.position_attribution_store import PositionAttributionStore
from app.services.strategy_bridge import StrategyBridge

router = APIRouter()


def get_bridge(settings: Settings = Depends(get_settings)) -> StrategyBridge:
    client = OKKClient(
        base_url=settings.okk_api_base_url,
        token=settings.okk_api_token,
        user_id=settings.okk_user_id,
        timeout_seconds=settings.command_timeout_seconds,
    )
    attribution_store = PositionAttributionStore(settings.attribution_file)
    return StrategyBridge(client, attribution_store)


def get_attribution_store(
    settings: Settings = Depends(get_settings),
) -> PositionAttributionStore:
    return PositionAttributionStore(settings.attribution_file)


@router.get("/status")
async def get_okk_status(bridge: StrategyBridge = Depends(get_bridge)) -> dict:
    return await bridge.status()


@router.get("/overview")
async def get_okk_overview(bridge: StrategyBridge = Depends(get_bridge)) -> dict:
    return await bridge.overview()


@router.get("/strategies/{strategy_id}/advice")
async def get_strategy_advice(
    strategy_id: int, bridge: StrategyBridge = Depends(get_bridge)
) -> dict:
    return await bridge.strategy_advice(strategy_id)


@router.get("/position-attributions")
async def list_position_attributions(
    store: PositionAttributionStore = Depends(get_attribution_store),
) -> dict:
    return {"items": store.list()}


@router.put("/position-attributions/{position_key}")
async def update_position_attribution(
    position_key: str,
    payload: PositionAttributionUpdate,
    store: PositionAttributionStore = Depends(get_attribution_store),
) -> dict:
    attribution = store.upsert(position_key, payload)
    return {"item": attribution}
