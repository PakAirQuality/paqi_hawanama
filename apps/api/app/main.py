import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import get_database
from app.routers import health, meta, nearest, current, history, dashboard, cities, exports, exports_publish, tasks, bot, punjab_epa, openaq_network, nasa_database, internal_stations, public, ops_pipeline, ops_downscaler, data_sources, analyst_desk, copilot, analytics, bam_ingest

# True only on the dedicated public BAM push-ingest service (hawanama-bam).
# Not mounted on the main public app, so BAM POST is isolated to its own service.
BAM_ROLE = os.environ.get("BAM_ROLE", "").lower() == "true"

app = FastAPI(
    title="Hawanama API",
    description="Air Quality Monitoring API for South Asia",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

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

@app.get("/")
async def root():
    return {"message": "Hawanama API", "version": "1.0.0"}