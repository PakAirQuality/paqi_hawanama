from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    model_config = ConfigDict(extra='ignore', env_file='.env')
    # Database - loaded from .env file
    POSTGRES_SERVER: str | None = None
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: str | None = None
    POSTGRES_DB: str | None = None
    POSTGRES_PORT: int = 5432
    
    # Redis
    REDIS_URL: str = "redis://localhost:6380"
    
    # External APIs
    IQAIR_API_KEY: Optional[str] = None
    OPENAQ_API_KEY: Optional[str] = None
    
    # API Endpoints
    IQAIR_BASE_URL: str = "http://api.airvisual.com/v2"
    OPENAQ_BASE_URL: str = "https://api.openaq.org/v2"
    
    # Rate Limiting (requests per minute)
    IQAIR_RATE_LIMIT: int = 10000  # IQAir allows 10k/month free tier
    OPENAQ_RATE_LIMIT: int = 2000  # OpenAQ is more generous
    
    # QC Thresholds
    PM25_MIN: float = 0.0
    PM25_MAX: float = 1000.0
    PM10_MIN: float = 0.0
    PM10_MAX: float = 2000.0
    TEMP_MIN: float = -50.0
    TEMP_MAX: float = 60.0
    HUMIDITY_MIN: float = 0.0
    HUMIDITY_MAX: float = 100.0
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


@lru_cache()
def get_settings() -> Settings:
    return Settings()  # will read env when first called, not at import time

# For backward compatibility with existing imports
settings = get_settings()