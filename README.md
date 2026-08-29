# Hawanama

Real-time air quality monitoring platform for South Asia. Collects, analyzes, and visualizes pollution data from 1,000+ monitoring stations across Pakistan, India, Bangladesh, Nepal, and Sri Lanka.

**Live:** [hawanama.org](https://hawanama.org) | **Dashboard:** [hawanama-dashboard.web.app](https://hawanama-dashboard.web.app)

---

## Architecture

```
IQAir API ──► Station Discovery ──► GCS Manifests
                                        │
                                   Data Ingestion
                                        │
                                   TimescaleDB
                                    (PostGIS)
                                        │
                                   FastAPI (Cloud Run)
                                   ┌────┴────┐
                              Web-Next    Dashboard
                            (public)     (internal)
```

## Project Structure

```
hawanama/
├── apps/
│   ├── api/                  # FastAPI backend — Cloud Run
│   ├── dashboard-frontend/   # Internal ops dashboard — Next.js
│   ├── web-next/             # Public website — Next.js
│   └── worker/               # Scheduled task definitions
├── db_schema/                # PostgreSQL/TimescaleDB schema
├── infra/                    # Terraform (Cloud Run, Scheduler)
├── scripts/                  # Data processing utilities
├── pak_boundaries/           # geoBoundaries GeoJSON
└── cloudbuild.yaml           # CI/CD pipeline
```

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **API** | Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Uvicorn |
| **Database** | PostgreSQL 17 + TimescaleDB + PostGIS |
| **Public Frontend** | Next.js 15, Mapbox GL, Deck.gl, Recharts |
| **Dashboard** | Next.js 16, shadcn/ui, ApexCharts, Mapbox GL |
| **Infrastructure** | Google Cloud Run, Cloud Build, Cloud Scheduler, GCS |
| **AI/ML** | Google Gemini, PydanticAI, custom PM2.5 forecasting models |
| **Data Sources** | IQAir API, NASA MODIS, Open-Meteo (ECMWF IFS), Punjab EPA |

## Key Features

### Data Pipeline
- **Hourly ingestion** from IQAir API across 5 South Asian countries
- **Station discovery** with GCS-backed manifests for distributed consistency
- **City/state/country aggregations** computed from station-level readings
- **CSV & Parquet exports** generated daily and stored in GCS

### Visualization
- **Interactive map** with real-time AQI station markers and clustering
- **Wind particle layer** — ECMWF IFS 0.25 wind data rendered as GPU particles via Deck.gl
- **Satellite PM2.5 overlay** — NASA V5GL04 HybridPM25 COGs served as XYZ raster tiles
- **Historical charts** — hourly, daily, and yearly AQI trends

### ML Operations
- **PM2.5 forecasting** — 3-day station-level predictions with risk bands
- **Analyst desk** — operational dashboard with watchlists, city summaries, and trend detection
- **AI copilot** — PydanticAI-powered streaming chat for forecast interpretation
- **Model lifecycle** — training, evaluation, and monitoring via Cloud Run jobs

### Twitter Bot
- **Persona-driven** LLM-generated tweets (Gemini API)
- **Smart triggers** — high smog alerts, volatility detection, hotspot warnings
- **Emergency mode** — automatic airpocalypse alerts when AQI > 500
- **Budget system** — ~500 posts/month with scheduled + reactive posting

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL with TimescaleDB and PostGIS extensions
- Google Cloud SDK (`gcloud`)
- Access to GCP project `hawanama-2`

### API (Backend)

```bash
cd apps/api

# Create virtual environment
python -m venv venv && source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env  # Edit with your credentials

# Run locally
uvicorn app.main:app --reload --port 8000
```

The API serves at `http://localhost:8000/api/v1/`. Interactive docs at `/api/v1/openapi.json`.

### Dashboard Frontend

```bash
cd apps/dashboard-frontend
npm install
npm run dev    # http://localhost:3000
```

### Public Website

```bash
cd apps/web-next
npm install
npm run dev    # http://localhost:3000
```

## Deployment

### API (Cloud Run)

```bash
# Build and deploy via Cloud Build
gcloud builds submit --config cloudbuild.yaml --project hawanama-2 --timeout=10m

# Verify
curl https://hawanama-152782825429.asia-south1.run.app/api/v1/health
```

The `cloudbuild.yaml` pipeline: **build** Docker image, **push** to Artifact Registry, **deploy** to Cloud Run with 100% traffic routing.

### Dashboard Frontend (Firebase)

```bash
cd apps/dashboard-frontend
npm run build
npx firebase deploy --only hosting  # → hawanama-dashboard.web.app
```

### Public Website (Firebase)

```bash
cd apps/web-next
npm run build
# Deploy to hawanama-2.web.app → hawanama.org
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_SERVER` | TimescaleDB host |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Database credentials |
| `POSTGRES_DB` / `POSTGRES_PORT` | Database name and port |
| `IQAIR_API_KEY` | IQAir API key for station data |
| `TASKS_API_SECRET` | Bearer token for protected task endpoints |
| `PUBLIC_API_SECRET` | API key for public data endpoints |
| `NASA_API_KEY` | NASA Database API access |
| `GEMINI_API_KEY` | Google Gemini for LLM features |
| `PUNJAB_EPA_API_KEY` | Punjab EPA data source |
| `REDIS_URL` | Redis connection string |
| `OPS_FORECASTS_BUCKET` | GCS bucket for ML forecasts |
| `OPS_MODELS_BUCKET` | GCS bucket for model artifacts |
| `MANIFEST_GCS_BUCKET` | GCS bucket for station manifests |

All secrets are managed via Google Secret Manager and injected at deploy time.

## API Endpoints

### Public (no auth)
- `GET /api/v1/meta/countries` — list countries
- `GET /api/v1/meta/provinces` — list provinces
- `GET /api/v1/meta/cities` — list cities (filterable by province)
- `GET /api/v1/meta/stations` — list stations (filterable by city)
- `GET /api/v1/stations/{id}/current` — current reading for a station
- `GET /api/v1/stations/{id}/history` — historical AQI data
- `GET /api/v1/cities/{city}/current` — current city AQI
- `GET /api/v1/nearest` — nearest station by coordinates
- `GET /api/v1/dashboard/stats` — dashboard summary stats

### Authenticated (API key or Bearer token)
- `GET /api/v1/public/locations` — all PAQI network locations
- `GET /api/v1/public/measurements` — measurements export
- `POST /api/v1/tasks/*` — ingestion and discovery tasks
- `POST /api/v1/bot/*` — Twitter bot operations
- `POST /api/v1/ops/analyst-desk/copilot/*` — AI copilot

## Database

PostgreSQL with TimescaleDB (time-series) and PostGIS (geospatial):

| Table | Purpose |
|-------|---------|
| `readings` | Hypertable — hourly PM2.5, AQI, meteorological data |
| `stations` | Monitoring station metadata and coordinates |
| `cities` / `states` / `countries` | Geographic hierarchy |
| `providers` | Data source registry (IQAir, EPA, etc.) |

Schema is defined in `db_schema/` and is **protected** — application code adapts to the schema, never the reverse.

## Contributing

This is a private repository maintained by the Pakistan Air Quality Initiative (PAQI). For questions or access, contact the maintainers.

## License

Private. All rights reserved.
