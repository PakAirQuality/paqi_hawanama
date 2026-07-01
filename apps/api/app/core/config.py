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
    ALLOWED_HOSTS: List[str] = [
        "https://hawanama.org",
        "https://www.hawanama.org",
        "https://hawanama-dashboard.web.app",
        "https://hawanama-2.web.app",
        "https://hawanama-152782825429.asia-south1.run.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    
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
    PUBLIC_API_SECRET: Optional[str] = None  # Secret for public API endpoints
    NASA_API_KEY: Optional[str] = None  # API key for NASA Database endpoints

    # BAM push-ingest (SFL / external MQTT bridge → HTTPS)
    BAM_INGEST_TOKEN: Optional[str] = None   # Bearer token SFL uses to push BAM readings
    BAM_ALLOWED_IPS: Optional[str] = None    # optional comma-separated source IP allowlist
    BAM_RATE_LIMIT_PER_MIN: int = 120        # best-effort per-instance rate limit
    
    # LLM/AI Services
    GEMINI_API_KEY: Optional[str] = None

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Ops Pipeline (ML estimation jobs)
    # Multi-bucket architecture for separation of concerns
    OPS_MODELS_BUCKET: Optional[str] = None  # GCS bucket for model artifacts (e.g., paqi-models-hawanama-data)
    OPS_OUTPUTS_BUCKET: Optional[str] = None  # GCS bucket for predictions and runs (e.g., paqi-outputs-hawanama-data)
    OPS_FEATURES_BUCKET: Optional[str] = None  # GCS bucket for COGs and training data (e.g., paqi-features-hawanama-data)
    OPS_DERIVED_BUCKET: Optional[str] = None  # GCS bucket for feature stores (e.g., paqi-derived-hawanama-data) - legacy/fallback
    OPS_FORECASTS_BUCKET: Optional[str] = None  # GCS bucket for PM2.5 forecasts (e.g., paqi-forecasts-hawanama-data)
    OPS_GCP_PROJECT: Optional[str] = None  # GCP project for Cloud Run jobs
    OPS_RUN_REGION: str = "asia-south1"  # Cloud Run region
    OPS_DAILY_JOB_NAME: str = "estimation-daily-pipeline"  # Daily estimation job name
    OPS_RETRAIN_JOB_NAME: str = "estimation-model-retrain"  # Model retrain job name
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"


settings = Settings()