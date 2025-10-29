from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Hawanama API"
    
    # Database - loaded from .env file
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int
    
    # Redis
    REDIS_URL: str = "redis://localhost:6380"
    
    # CORS
    ALLOWED_HOSTS: List[str] = ["*"]
    
    # API Keys
    IQAIR_API_KEY: Optional[str] = None
    OPENAQ_API_KEY: Optional[str] = None
    
    # Twitter API Keys (matching existing .env file naming)
    Bearer_token_twitter: Optional[str] = None
    API_Key_twitter: Optional[str] = None
    API_Key_Secret_twitter: Optional[str] = None
    Access_Token_twitter: Optional[str] = None
    Access_Token_Secret_twitter: Optional[str] = None
    
    # Security
    TASKS_API_SECRET: Optional[str] = None  # Secret for protecting tasks endpoints
    
    # LLM/AI Services
    GEMINI_API_KEY: Optional[str] = None
    
    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"


settings = Settings()