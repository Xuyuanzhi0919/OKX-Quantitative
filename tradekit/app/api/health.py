from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.services.okx_cli_adapter import OkxCliAdapter
from app.services.policy_guard import PolicyGuard

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    cli = OkxCliAdapter(settings.okx_cli_bin, settings.command_timeout_seconds)
    policy = PolicyGuard.from_file(settings.policy_file)
    cli_status = await cli.inspect()
    return {
        "service": settings.service_name,
        "okx_cli": cli_status,
        "policy": policy.summary(),
    }

