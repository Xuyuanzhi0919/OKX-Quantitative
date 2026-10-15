from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.services.okx_cli_adapter import OkxCliAdapter

router = APIRouter()


@router.get("/ticker/{inst_id}")
async def get_ticker(inst_id: str, settings: Settings = Depends(get_settings)) -> dict:
    cli = OkxCliAdapter(settings.okx_cli_bin, settings.command_timeout_seconds)
    return await cli.run(["market", "ticker", inst_id])

