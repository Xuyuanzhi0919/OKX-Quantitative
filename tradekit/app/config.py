from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "OKK TradeKit Gateway"
    okx_cli_bin: str = Field(default="okx", validation_alias="OKX_CLI_BIN")
    okk_api_base_url: str = Field(default="http://127.0.0.1:8000/api/v1", validation_alias="OKK_API_BASE_URL")
    okk_api_token: str | None = Field(default=None, validation_alias="OKK_API_TOKEN")
    okk_user_id: int = Field(default=1, validation_alias="OKK_USER_ID")
    attribution_file: Path = Field(
        default=Path(__file__).resolve().parents[1] / "data" / "position_attributions.json",
        validation_alias="TRADEKIT_ATTRIBUTION_FILE",
    )
    policy_file: Path = Field(
        default=Path(__file__).resolve().parents[1] / "config" / "policy.example.yaml",
        validation_alias="TRADEKIT_POLICY_FILE",
    )
    command_timeout_seconds: float = Field(default=20.0, validation_alias="TRADEKIT_COMMAND_TIMEOUT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
