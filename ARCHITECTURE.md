# Hawanama Architecture Documentation

## Overview
Hawanama is a modern, scalable air quality monitoring platform built for Pakistan. The architecture follows microservices principles with clear separation of concerns.

## System Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend API   │    │   Data Workers  │
│   (Next.js)     │    │   (FastAPI)     │    │   (Celery)      │
│                 │    │                 │    │                 │
│ - MapLibre Maps │◄──►│ - REST APIs     │◄──►│ - IQAir Fetch   │
│ - Vector Tiles  │    │ - Type Safety   │    │ - Quality Control│
│ - Real-time UI  │    │ - Validation    │    │ - Backfill Jobs │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       ▼                       ▼
         │              ┌─────────────────┐    ┌─────────────────┐
         │              │   PostgreSQL    │    │     Redis       │
         │              │ + TimescaleDB   │    │                 │
         │              │ + PostGIS       │    │ - Job Queue     │
         │              │                 │    │ - Rate Limiting │
         │              │ - Time Series   │    │ - Caching       │
         │              │ - Spatial Data  │    │ - Sessions      │
         │              │ - TimescaleDB   │    │                 │
         │              └─────────────────┘    └─────────────────┘
         │                       │
         └──────────────────────►│
```

## Component Details

### Frontend (`apps/web-next/`)
**Technology**: Next.js 14, TypeScript, TailwindCSS, MapLibre GL JS

**Responsibilities**:
- Interactive air quality maps with client-side clustering
- Real-time data visualization
- Station detail views with historical charts
- City-level summaries and rankings
- Responsive design for mobile/desktop

**Key Features**:
- Server-side rendering for SEO
- Client-side clustering for performance
- Real-time updates via API polling
- Offline-capable PWA (planned)

### Backend API (`apps/api/`)
**Technology**: FastAPI, Pydantic v2, PostgreSQL, AsyncIO

**Responsibilities**:
- RESTful API endpoints for frontend
- Data validation and type safety
- Authentication and authorization
- Rate limiting and caching
- OpenAPI documentation

**Endpoints**:
- `/health` - System health checks
- `/api/v1/stations` - Station metadata and locations
- `/api/v1/readings` - Time-series air quality data
- `/api/v1/cities` - City-level aggregations (planned)
- `/api/v1/exports` - Data export functionality (planned)

### Data Workers (`apps/worker/`)
**Technology**: APScheduler, Redis, httpx, tenacity

**Responsibilities**:
- External API integration (IQAir, OpenAQ)
- Data ingestion with rate limiting
- Quality control and validation
- Automated backfill of missing data
- Data reconciliation between sources

**Jobs**:
- `sync_stations` - Hourly station metadata refresh
- `fetch_minute_readings` - Real-time data collection (2min interval)
- `fetch_hourly_readings` - Hourly data reconciliation (5min interval)
- `validate_readings` - Quality control processing (10min interval)

### Database Layer
**Technology**: PostgreSQL 16, TimescaleDB, PostGIS

**Optimization**:
- **TimescaleDB**: Hypertables for time-series data with automatic partitioning
- **PostGIS**: Spatial indexing and geographic queries
- **Continuous Aggregates**: Pre-computed hourly and daily rollups
- **Indexing**: Optimized for time-range and spatial queries

**Schema**:
```sql
-- Core tables
monitor_sources(id, name, type)
stations(id, source_id, external_id, name, city_id, geom, meta_json)
cities(id, name, country, geom)

-- Time-series data (hypertables)
readings_minute(station_id, ts, pm25, pm10, o3, no2, so2, co, temp, hum, aqi_raw, qc_state, origin, payload_json)
readings_hour(station_id, ts, ...)

-- Aggregated views
agg_hour (continuous aggregate from readings_minute)
agg_day (continuous aggregate from readings_hour)

-- Spatial views for API endpoints
stations_with_latest (stations with most recent readings for map display)
```

## Data Flow

### Ingestion Pipeline
```
IQAir API → Rate Limiter → Data Parser → QC Engine → Database
    ↓           (Redis)      (Worker)     (Rules)     (TimescaleDB)
OpenAQ API                                             ↓
                                              ┌─────────────────┐
                                              │ Continuous      │
                                              │ Aggregates      │
                                              │ (1h, 24h)       │
                                              └─────────────────┘
```

### Quality Control Pipeline
```
Raw Reading → Range Check → Spike Detection → Flatline Detection → QC Score
     ↓             ↓              ↓                 ↓              ↓
   Valid?      Physical       Statistical      Sensor          OK/SUSPECT/BAD
              Bounds         Anomaly          Malfunction
```

### Frontend Data Flow
```
User Request → Next.js SSR → API Call → PostgreSQL → JSON Response → React Render
     ↓
Map Interaction → API Request → PostgreSQL → GeoJSON Response → MapLibre + Supercluster
```

## Deployment Architecture

### Local Development
- **Docker Compose**: All services in containers
- **Hot Reload**: API and frontend with live reload
- **Sample Data**: Automated seeding for development

### Production (Planned)
- **Frontend**: Vercel (Edge deployment)
- **API**: Fly.io/Render (Container deployment)
- **Database**: TimescaleDB Cloud (Managed service)
- **Workers**: Same infrastructure as API
- **Monitoring**: Prometheus + Grafana
- **CDN**: Cloudflare (Caching, DDoS protection)

## Security Considerations

### Data Protection
- No PII collected
- API keys stored in environment variables
- Rate limiting on all endpoints
- CORS restrictions in production

### Quality Assurance
- Type safety with TypeScript and Pydantic
- Automated testing (planned)
- Database migrations with Alembic
- Structured logging for debugging

## Scalability Features

### Performance Optimizations
- Client-side clustering for map rendering
- Database query optimization with proper indexing
- Redis caching for frequently accessed data
- Continuous aggregates for historical queries

### Horizontal Scaling
- Stateless API design
- APScheduler workers can run on multiple instances
- Database read replicas support (TimescaleDB)
- CDN for static assets

## Monitoring & Observability (Planned)

### Metrics
- API response times and error rates
- Data ingestion lag and success rates
- Quality control coverage percentages
- Database performance metrics

### Alerting
- Data source outages
- Quality control failures
- System performance degradation
- API rate limit approaches

## Extension Points

### New Data Sources
- Standardized ingestion interface
- Configurable QC rules per source
- Source-specific metadata handling

### Additional Pollutants
- Schema supports extensible pollutant types
- Frontend visualization adapts automatically
- QC rules configurable per pollutant

### Geographic Expansion
- Multi-country support built-in
- Timezone handling for global deployment
- Localization framework ready