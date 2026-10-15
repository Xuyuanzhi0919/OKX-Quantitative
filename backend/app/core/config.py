# -*- coding: utf-8 -*-
"""
Core configuration file - loads all settings from .env
"""
from pydantic_settings import BaseSettings
from typing import Optional, List
import json


class Settings(BaseSettings):
    """Application configuration - all values loaded from .env file"""

    # Application
    APP_NAME: str
    APP_VERSION: str
    DEBUG: bool

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int
    REDIS_PASSWORD: Optional[str] = None

    # JWT
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    API_ACCESS_TOKEN: Optional[str] = None
    MOBILE_READ_TOKEN: Optional[str] = None

    # OKX API
    OKX_API_KEY: Optional[str] = None
    OKX_SECRET_KEY: Optional[str] = None
    OKX_PASSPHRASE: Optional[str] = None
    OKX_SIMULATED: bool = False
    OKX_PROXY: Optional[str] = None

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # CORS
    CORS_ORIGINS: str

    # DeepSeek LLM (Phase 2)
    DEEPSEEK_API_KEY: Optional[str] = None

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS from JSON string to list"""
        if isinstance(self.CORS_ORIGINS, str):
            return json.loads(self.CORS_ORIGINS)
        return self.CORS_ORIGINS

    class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = "utf-8"


settings = Settings()
