from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.services.okx_cli_adapter import OkxCliAdapter

router = APIRouter()


@router.get("/balance")
async def get_balance(settings: Settings = Depends(get_settings)) -> dict:
    cli = OkxCliAdapter(settings.okx_cli_bin, settings.command_timeout_seconds)
    return await cli.run(["account", "balance"])
