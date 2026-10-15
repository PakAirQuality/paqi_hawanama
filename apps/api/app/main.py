import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.database import get_database
from app.ingestion.http import aclose_shared_clients, configure_logging

# Process-wide logging: redacts credentials in every record and keeps httpx from
# logging request URLs (which carry the IQAir key as a query parameter).
configure_logging(settings.LOG_LEVEL, secrets=(settings.IQAIR_API_KEY, settings.OPENAQ_API_KEY))
from app.routers import health, meta, nearest, current, history, dashboard, cities, exports, exports_publish, tasks, bot, punjab_epa, openaq_network, nasa_database, internal_stations, public, ops_pipeline, ops_downscaler, data_sources, analyst_desk, copilot, analytics, bam_ingest

# True only on the dedicated ingestion Cloud Run service (hawanama-ingest).
# Public read API does not expose POST /tasks/* — schedulers call ingest directly.
INGEST_ROLE = os.environ.get("INGEST_ROLE", "").lower() == "true"

# True only on the dedicated public BAM push-ingest service (hawanama-bam).
# Not mounted on the main public app, so BAM POST is isolated to its own service.
BAM_ROLE = os.environ.get("BAM_ROLE", "").lower() == "true"

app = FastAPI(
    title="Hawanama API",
    description="Air Quality Monitoring API for South Asia",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Compress JSON responses (the /dashboard/stations payload was 440 KB uncompressed).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Rate limiting for the public partner API (/api/v1/public/*).
# The limiter instance lives in the public router; register it on the app and
# wire the 429 handler so @limiter.limit decorators take effect.
app.state.limiter = public.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Baseline security headers on every response.
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers  
app.include_router(health.router, prefix=f"{settings.API_V1_STR}/health", tags=["health"])
app.include_router(meta.router, prefix=f"{settings.API_V1_STR}/meta", tags=["metadata"])
# app.include_router(directory.router, prefix=f"{settings.API_V1_STR}", tags=["directory"])  # Temporarily disabled
app.include_router(nearest.router, prefix=f"{settings.API_V1_STR}", tags=["nearest"])
app.include_router(current.router, prefix=f"{settings.API_V1_STR}", tags=["current"])
app.include_router(history.router, prefix=f"{settings.API_V1_STR}", tags=["history"])
app.include_router(dashboard.router, prefix=f"{settings.API_V1_STR}/dashboard", tags=["dashboard"])
app.include_router(cities.router, prefix=f"{settings.API_V1_STR}", tags=["cities"])
app.include_router(exports.router, prefix=f"{settings.API_V1_STR}/exports", tags=["exports"])
app.include_router(exports_publish.router, prefix=f"{settings.API_V1_STR}/exports/publish", tags=["publish"])
if INGEST_ROLE:
    app.include_router(tasks.router, prefix=f"{settings.API_V1_STR}", tags=["tasks"])
if BAM_ROLE:
    app.include_router(bam_ingest.router, prefix=f"{settings.API_V1_STR}/bam", tags=["bam-ingest"])
app.include_router(bot.router, prefix=f"{settings.API_V1_STR}", tags=["bot"])
app.include_router(punjab_epa.router, prefix=f"{settings.API_V1_STR}/punjab", tags=["punjab-epa"])
app.include_router(openaq_network.router, prefix=f"{settings.API_V1_STR}")
app.include_router(nasa_database.router, prefix=f"{settings.API_V1_STR}")
app.include_router(internal_stations.router, prefix=f"{settings.API_V1_STR}/internal/stations", tags=["internal-stations"])
app.include_router(public.router, prefix=f"{settings.API_V1_STR}", tags=["public"])
app.include_router(ops_pipeline.router, prefix=f"{settings.API_V1_STR}/ops/pipeline", tags=["ops-pipeline"])
app.include_router(ops_downscaler.router, prefix=f"{settings.API_V1_STR}/ops/downscaler", tags=["ops-downscaler"])
app.include_router(data_sources.router, prefix=f"{settings.API_V1_STR}/data-sources", tags=["data-sources"])
app.include_router(analyst_desk.router, prefix=f"{settings.API_V1_STR}/ops/analyst-desk", tags=["analyst-desk"])
app.include_router(copilot.router, prefix=f"{settings.API_V1_STR}/ops/analyst-desk", tags=["copilot"])
app.include_router(analytics.router, prefix=f"{settings.API_V1_STR}/ops/analyst-desk", tags=["analytics"])

# Add direct stations endpoint for frontend compatibility
@app.get(f"{settings.API_V1_STR}/stations")
async def get_stations_list(db = Depends(get_database)):
    """Get stations data for frontend - delegates to dashboard"""
    from app.routers.dashboard import get_stations_for_map
    return await get_stations_for_map(db)

@app.on_event("shutdown")
async def _close_shared_http_clients():
    await aclose_shared_clients()


@app.get("/")
async def root():
    return {"message": "Hawanama API", "version": "1.0.0"}