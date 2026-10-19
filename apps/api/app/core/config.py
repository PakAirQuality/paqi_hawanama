from pydantic import field_validator
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

    # Secret Manager values created with `echo` carry a trailing newline; a bearer header can
    # never contain one, so every constant-time comparison would fail. Strip surrounding
    # whitespace from every secret and key before use.
    @field_validator(
        "TASKS_API_SECRET", "PUBLIC_API_SECRET", "PARTNER_API_KEYS", "NASA_API_KEY",
        "BAM_INGEST_TOKEN", "GEMINI_API_KEY", "IQAIR_API_KEY", "OPENAQ_API_KEY",
        "FIRMS_MAP_KEY", "PUNJAB_EPA_API_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY",
        mode="before", check_fields=False,
    )
    @classmethod
    def _strip_secret(cls, v):
        return v.strip() if isinstance(v, str) else v
    # Cloud Scheduler calls hawanama-ingest with an OIDC token for this service account and
    # this audience; the ingest role verifies both (app/core/security.py).
    SCHEDULER_SERVICE_ACCOUNT: str = "scheduler-invoker@hawanama-2.iam.gserviceaccount.com"
    INGEST_BASE_URL: str = "https://hawanama-ingest-152782825429.asia-south1.run.app"
    # GCS destinations the publish routes may write to: "bucket" or "bucket/prefix", comma-separated.
    EXPORT_GCS_ALLOWED: str = "paqi-raw-hawanama-data"
    PUBLIC_API_SECRET: Optional[str] = None  # Legacy single shared key for public API endpoints
    # Per-partner API keys for the public partner API. JSON object mapping
    # key -> partner name, e.g. '{"abc123": "alertli", "def456": "delivetree"}'.
    # Lets us issue/revoke/attribute keys per partner without a DB table.
    PARTNER_API_KEYS: Optional[str] = None
    NASA_API_KEY: Optional[str] = None  # API key for NASA Database endpoints

    # BAM push-ingest (SFL / external MQTT bridge → HTTPS)
    BAM_INGEST_TOKEN: Optional[str] = None   # Bearer token SFL uses to push BAM readings
    BAM_ALLOWED_IPS: Optional[str] = None    # optional comma-separated source IP allowlist
    BAM_RATE_LIMIT_PER_MIN: int = 120        # best-effort per-instance rate limit
    
    # LLM/AI Services
    GEMINI_API_KEY: Optional[str] = None

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60            # partner API (/public/*), per key or IP
    PUBLIC_RATE_LIMIT_PER_MINUTE: int = 120    # JSON read routes used by the sites, per IP per instance
    TILE_RATE_LIMIT_PER_MINUTE: int = 900      # raster/tile routers (a map view fetches dozens per pan)

    # Public copilot budget (paid Gemini calls; counters in ops.copilot_usage, migration 004)
    COPILOT_IP_DAILY_LIMIT: int = 20              # requests per client IP per UTC day
    COPILOT_GLOBAL_DAILY_REQUESTS: int = 500      # requests across all clients per UTC day
    COPILOT_GLOBAL_DAILY_TOKENS: int = 2_000_000  # prompt+completion tokens per UTC day
    COPILOT_RATE_LIMIT_PER_MINUTE: int = 6        # burst guard per IP per instance
    COPILOT_MAX_MESSAGE_CHARS: int = 2000

    # Ops Pipeline (ML estimation jobs)
    # Multi-bucket architecture for separation of concerns
    OPS_MODELS_BUCKET: Optional[str] = None  # GCS bucket for model artifacts (e.g., paqi-models-hawanama-data)
    OPS_OUTPUTS_BUCKET: Optional[str] = None  # GCS bucket for predictions and runs (e.g., paqi-outputs-hawanama-data)
    OPS_FEATURES_BUCKET: Optional[str] = None  # GCS bucket for COGs and training data (e.g., paqi-features-hawanama-data)
    OPS_DERIVED_BUCKET: Optional[str] = None  # GCS bucket for feature stores (e.g., paqi-derived-hawanama-data) - legacy/fallback
    OPS_FORECASTS_BUCKET: Optional[str] = None  # GCS bucket for PM2.5 forecasts (e.g., paqi-forecasts-hawanama-data)
    FIRMS_MAP_KEY: Optional[str] = None  # NASA FIRMS API key for active fire data
    OPS_GCP_PROJECT: Optional[str] = None  # GCP project for Cloud Run jobs
    OPS_RUN_REGION: str = "asia-south1"  # Cloud Run region
    OPS_DAILY_JOB_NAME: str = "estimation-daily-pipeline"  # Daily estimation job name
    OPS_RETRAIN_JOB_NAME: str = "estimation-model-retrain"  # Model retrain job name

    # ------------------------------------------------------------------
    # Ingestion. These are the only source of truth for the ingestion tasks
    # and provider clients; nothing under app/ingestion reads os.environ.
    # Env var names are unchanged from what cloudbuild.yaml already sets.
    # ------------------------------------------------------------------
    # Provider: IQAir
    IQAIR_BASE_URL: str = "https://api.airvisual.com/v2"
    IQAIR_CREDENTIAL_ALIAS: str = "iqair-default"   # shared-quota bucket; change when the key rotates
    IQAIR_MAX_CALLS_PER_MIN: int = 90                # cloudbuild sets 500; confirm against the IQAir plan
    IQAIR_CONCURRENCY: int = 6                       # HTTP requests in flight inside the client
    IQAIR_HTTP_CONNECT_TIMEOUT_S: float = 10.0
    IQAIR_HTTP_READ_TIMEOUT_S: float = 30.0
    IQAIR_RETRY_MAX_ATTEMPTS: int = 4
    IQAIR_RETRY_MAX_WAIT_S: float = 20.0
    IQAIR_QUOTA_MAX_WAIT_S: float = 180.0            # give up waiting for a shared-quota slot after this
    IQAIR_BACKFILL_HOURS: int = 48
    IQAIR_COUNTRIES: Optional[str] = None            # comma-separated; see app.core.south_asia
    # Provider: Punjab EPA (separate credential and endpoint; never routed through IQAir)
    PUNJAB_EPA_API_KEY: Optional[str] = None
    PUNJAB_EPA_API_BASE: str = "https://aqipunjab.com/api"
    PUNJAB_EPA_TIMEOUT_S: float = 30.0
    PUNJAB_EPA_PACING_S: float = 0.25
    # Provider: OpenAQ v3 — independent source, own key (X-API-Key), shadow mode until cutover.
    # Official defaults are 60 requests/min and 2,000/hour per key; targets below leave headroom
    # for retries and discovery. Never rotate/multiplex keys to evade limits.
    OPENAQ_ENABLED: bool = False
    OPENAQ_BASE_URL: str = "https://api.openaq.org/v3"
    OPENAQ_CREDENTIAL_ALIAS: str = "openaq-default"
    OPENAQ_COUNTRY_ISO: str = "PK"                   # /v3/locations?iso=
    OPENAQ_PARAMETERS: str = "pm25"                  # comma-separated parameter names to ingest
    OPENAQ_RATE_PER_MIN: int = 45
    OPENAQ_RATE_PER_HOUR: int = 1500
    OPENAQ_MAX_REQUESTS_PER_RUN: int = 1200          # hard cap per invocation
    OPENAQ_PAGE_LIMIT: int = 1000                    # documented maximum
    OPENAQ_MAX_PAGES_PER_STREAM: int = 6
    OPENAQ_OVERLAP_HOURS: int = 72                   # re-read window for late/revised data
    OPENAQ_WINDOW_HOURS: int = 24                    # forward step per run beyond the checkpoint
    OPENAQ_INITIAL_BACKFILL_HOURS: int = 72          # first window for a new stream
    OPENAQ_RECONCILE_LOOKBACK_DAYS: int = 14
    OPENAQ_SELF_PROVIDER_NAMES: str = "PAQI,Pakistan Air Quality Initiative,Hawanama"   # our own data seen via OpenAQ
    OPENAQ_ALIAS_DISTANCE_M: float = 150.0
    OPENAQ_HTTP_TIMEOUT_S: float = 30.0
    OPENAQ_RETIRE_AFTER_MISSED_RUNS: int = 7
    # Ingestion behaviour
    INGEST_CONCURRENCY: int = 6                      # entities (stations/cities) in flight per task
    ALLOW_DB_STATION_FALLBACK: bool = False
    ALLOW_DB_CITY_FALLBACK: bool = False
    ALLOW_CITY_FALLBACK: bool = False
    ALLOW_STATE_ALIAS: bool = True
    ALLOW_NEAREST_FALLBACK: bool = False
    STATION_PROVIDER_CODE: str = "airvisual"
    DISCOVERY_COUNTRY: Optional[str] = None
    DISCOVERY_STATE: Optional[str] = None
    # Manifests / run artifacts
    MANIFEST_GCS_BUCKET: Optional[str] = None
    STATION_MANIFEST_DIR: str = "artifacts/station_manifests"
    CITY_MANIFEST_DIR: str = "artifacts/city_manifests"
    STATION_MANIFEST_FORMAT: str = "parquet"         # parquet | jsonl
    CITY_MANIFEST_FORMAT: Optional[str] = None       # defaults to STATION_MANIFEST_FORMAT
    INGEST_OUT_DIR: str = "artifacts/ingest_runs"
    # Raw provider payload archive (gzip JSON in GCS, indexed in ops.raw_payloads)
    RAW_ARCHIVE_ENABLED: bool = True
    OPS_RAW_PAYLOADS_BUCKET: Optional[str] = None     # falls back to MANIFEST_GCS_BUCKET
    OPS_RAW_PAYLOADS_PREFIX: str = "raw_payloads"
    # ops schema (db_schema/migrations/001_ops_ingestion.sql)
    INGEST_LEASE_TTL_S: int = 3300                   # must stay below the Cloud Run request timeout (3600)
    OPS_TABLES_REQUIRED: bool = True                 # quota: fail loudly if ops.* is missing; runs/leases warn and continue
    # Health: max observation age per readings.source before /health/freshness reports degraded
    FRESHNESS_MAX_AGE_MIN: str = '{"airvisual": 180, "punjab": 180, "bam": 180, "default": 360}'
    LOG_LEVEL: str = "INFO"
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"


settings = Settings()