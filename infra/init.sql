-- =============================================================================
-- Hawanama Air Quality API - Production PostgreSQL + TimescaleDB + PostGIS Schema
-- Fixed version addressing PostgreSQL compatibility issues
-- =============================================================================

-- =============================================================================
-- 0) Extensions & Types
-- =============================================================================

-- Core extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- for digest() station ID generation
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- for fuzzy search

-- Custom enums and types
DO $$ BEGIN
  CREATE TYPE scope_type AS ENUM ('city','station');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE forecast_kind AS ENUM ('hourly','daily');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE pollutant_code AS ENUM ('pm25','pm10','o3','no2','so2','co');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- =============================================================================
-- 1) Providers & Directory (countries/states/cities/stations)
-- =============================================================================

-- Data providers (e.g., 'airvisual', 'purpleair', etc.)
CREATE TABLE IF NOT EXISTS providers (
  id              SMALLSERIAL PRIMARY KEY,
  code            TEXT UNIQUE NOT NULL,     -- 'airvisual'
  display_name    TEXT NOT NULL,            -- 'AirVisual by IQAir'
  api_url         TEXT,                     -- base API URL
  metadata        JSONB,                    -- provider-specific config
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Insert default provider
INSERT INTO providers (code, display_name, api_url) VALUES 
  ('airvisual', 'AirVisual by IQAir', 'https://api.airvisual.com/v2') 
ON CONFLICT (code) DO NOTHING;

-- Countries with optional ISO codes and boundaries
CREATE TABLE IF NOT EXISTS countries (
  id              BIGSERIAL PRIMARY KEY,
  name            TEXT UNIQUE NOT NULL,     -- 'Pakistan' (canonical English name)
  iso2            CHAR(2),                  -- 'PK'
  iso3            CHAR(3),                  -- 'PAK'
  geom            GEOGRAPHY(MULTIPOLYGON,4326),  -- admin boundary if available
  centroid        GEOGRAPHY(POINT,4326),         -- geographic center
  population      BIGINT,                   -- total population
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at    TIMESTAMPTZ,              -- last time we saw data for this country
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- States/provinces/regions
CREATE TABLE IF NOT EXISTS states (
  id              BIGSERIAL PRIMARY KEY,
  country_id      BIGINT NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,            -- 'Punjab'
  code            TEXT,                     -- optional state code
  geom            GEOGRAPHY(MULTIPOLYGON,4326),  -- state boundary
  centroid        GEOGRAPHY(POINT,4326),         -- geographic center
  population      BIGINT,                   -- state population
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(country_id, name)
);

-- Cities with normalized scope keys for API consistency
CREATE TABLE IF NOT EXISTS cities (
  id              BIGSERIAL PRIMARY KEY,
  country_id      BIGINT NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
  state_id        BIGINT REFERENCES states(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,            -- 'Lahore'
  geom            GEOGRAPHY(MULTIPOLYGON,4326),  -- city boundary if available
  centroid        GEOGRAPHY(POINT,4326),         -- city center point
  population      BIGINT,                   -- city population
  timezone        TEXT,                     -- 'Asia/Karachi'
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  -- Normalized stable key for API: 'country|state|city' (lowercase)
  -- Will be populated via trigger function instead of generated column
  scope_key       TEXT,
  
  UNIQUE(country_id, state_id, name)
);

-- Function to generate scope_key for cities
CREATE OR REPLACE FUNCTION update_city_scope_key()
RETURNS TRIGGER AS $$
BEGIN
  NEW.scope_key := lower(
    coalesce((SELECT c.name FROM countries c WHERE c.id = NEW.country_id),'') || '|' ||
    coalesce((SELECT s.name FROM states s WHERE s.id = NEW.state_id),'') || '|' ||
    NEW.name
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update scope_key
CREATE TRIGGER trigger_update_city_scope_key
  BEFORE INSERT OR UPDATE ON cities
  FOR EACH ROW EXECUTE FUNCTION update_city_scope_key();

-- Monitoring stations with 16-character hex IDs
CREATE TABLE IF NOT EXISTS stations (
  station_id      CHAR(16) PRIMARY KEY,     -- SHA1 hash of identifying attributes (first 16 chars)
  country_id      BIGINT NOT NULL REFERENCES countries(id) ON DELETE RESTRICT,
  state_id        BIGINT REFERENCES states(id) ON DELETE SET NULL,
  city_id         BIGINT REFERENCES cities(id) ON DELETE SET NULL,
  name            TEXT NOT NULL,            -- 'US Embassy Islamabad'
  lat             DOUBLE PRECISION NOT NULL,
  lon             DOUBLE PRECISION NOT NULL,
  
  -- PostGIS geometry column (auto-generated from lat/lon)
  geom            GEOGRAPHY(POINT,4326) GENERATED ALWAYS AS (
    ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
  ) STORED,
  
  provider_id     SMALLINT NOT NULL REFERENCES providers(id) ON DELETE RESTRICT,
  source_station_id TEXT,                   -- provider's native station ID
  elevation_m     DOUBLE PRECISION,         -- elevation above sea level
  metadata_json   JSONB,                    -- raw upstream station metadata
  timezone        TEXT,                     -- station timezone if different from city
  active          BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  -- Ensure uniqueness by provider and source ID
  UNIQUE(provider_id, source_station_id),
  -- Ensure uniqueness by geographic location and name
  UNIQUE(country_id, state_id, city_id, name, lat, lon)
);

-- Optional: Station version history for tracking changes
CREATE TABLE IF NOT EXISTS station_versions (
  id              BIGSERIAL PRIMARY KEY,
  station_id      CHAR(16) REFERENCES stations(station_id) ON DELETE CASCADE,
  valid_from      TIMESTAMPTZ NOT NULL,
  valid_to        TIMESTAMPTZ,              -- NULL = current version
  name            TEXT,
  lat             DOUBLE PRECISION,
  lon             DOUBLE PRECISION,
  metadata_json   JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- 2) Performance Indexes for Directory Tables
-- =============================================================================

-- Geographic indexes
CREATE INDEX IF NOT EXISTS idx_countries_geom   ON countries USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_countries_centroid ON countries USING GIST(centroid);
CREATE INDEX IF NOT EXISTS idx_states_geom      ON states USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_states_centroid  ON states USING GIST(centroid);
CREATE INDEX IF NOT EXISTS idx_cities_geom      ON cities USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_cities_centroid  ON cities USING GIST(centroid);
CREATE INDEX IF NOT EXISTS idx_stations_geom    ON stations USING GIST(geom);

-- API lookup indexes
CREATE INDEX IF NOT EXISTS idx_cities_scopekey  ON cities (scope_key);
CREATE INDEX IF NOT EXISTS idx_states_country   ON states (country_id);
CREATE INDEX IF NOT EXISTS idx_cities_country   ON cities (country_id);
CREATE INDEX IF NOT EXISTS idx_cities_state     ON cities (state_id);
CREATE INDEX IF NOT EXISTS idx_stations_city    ON stations (city_id);
CREATE INDEX IF NOT EXISTS idx_stations_provider ON stations (provider_id);

-- Full-text search indexes
CREATE INDEX IF NOT EXISTS idx_countries_name_trgm ON countries USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_states_name_trgm    ON states USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_cities_name_trgm    ON cities USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_stations_name_trgm  ON stations USING gin (name gin_trgm_ops);

-- =============================================================================
-- 3) Readings Table (TimescaleDB Hypertable)
-- =============================================================================

-- Main readings table for current conditions and historical data
CREATE TABLE IF NOT EXISTS readings (
  -- Scope identification
  scope_type      scope_type NOT NULL,      -- 'city' | 'station'
  scope_key       TEXT NOT NULL,            -- city: scope_key from cities table | station: station_id
  ts_utc          TIMESTAMPTZ NOT NULL,     -- timestamp aligned to top-of-hour
  
  -- Air Quality Index values
  aqi_us          SMALLINT,                 -- US EPA AQI (0-500+)
  aqi_cn          SMALLINT,                 -- China MEE AQI (0-500+)
  main_us         pollutant_code,           -- main pollutant for US AQI
  main_cn         pollutant_code,           -- main pollutant for CN AQI
  
  -- Pollutant concentrations (normalized to standard units)
  pm25            DOUBLE PRECISION,         -- PM2.5 concentration
  pm10            DOUBLE PRECISION,         -- PM10 concentration
  o3              DOUBLE PRECISION,         -- Ozone concentration
  no2             DOUBLE PRECISION,         -- Nitrogen dioxide concentration
  so2             DOUBLE PRECISION,         -- Sulfur dioxide concentration
  co              DOUBLE PRECISION,         -- Carbon monoxide concentration
  
  -- Units for pollutant concentrations (can vary by provider)
  units_pm25      TEXT DEFAULT 'µg/m³',
  units_pm10      TEXT DEFAULT 'µg/m³',
  units_o3        TEXT,                     -- 'ppb' or 'µg/m³'
  units_no2       TEXT,                     -- 'ppb' or 'µg/m³'
  units_so2       TEXT,                     -- 'ppb' or 'µg/m³'
  units_co        TEXT,                     -- 'ppm' or 'mg/m³'
  
  -- Meteorological data
  temp_c          DOUBLE PRECISION,         -- Temperature in Celsius
  humidity        DOUBLE PRECISION,         -- Relative humidity (%)
  pressure_hpa    DOUBLE PRECISION,         -- Atmospheric pressure (hPa)
  wind_speed_ms   DOUBLE PRECISION,         -- Wind speed (m/s)
  wind_dir_deg    INTEGER,                  -- Wind direction (degrees)
  weather_icon    TEXT,                     -- Weather icon code
  heatindex_c     DOUBLE PRECISION,         -- Heat index in Celsius
  dewpoint_c      DOUBLE PRECISION,         -- Dew point in Celsius
  visibility_km   DOUBLE PRECISION,         -- Visibility in kilometers
  uv_index        DOUBLE PRECISION,         -- UV index
  pop_pct         SMALLINT,                 -- Probability of precipitation (%)
  
  -- Quality control and provenance
  qc_state        TEXT,                     -- 'OK' | 'SUSPECT' | 'INVALID' | 'MISSING'
  qc_flags        TEXT[],                   -- array of QC flag codes
  source          TEXT NOT NULL DEFAULT 'airvisual',
  raw             JSONB,                    -- complete raw upstream response
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  -- Primary key ensures deduplication
  PRIMARY KEY (scope_type, scope_key, ts_utc)
);

-- Convert to TimescaleDB hypertable
SELECT create_hypertable('readings', by_range('ts_utc'), if_not_exists => TRUE);

-- =============================================================================
-- 4) Performance Indexes and Policies for Readings
-- =============================================================================

-- Optimized indexes for API queries
CREATE INDEX IF NOT EXISTS idx_readings_city_recent 
  ON readings (scope_key, ts_utc DESC) 
  WHERE scope_type = 'city';

CREATE INDEX IF NOT EXISTS idx_readings_station_recent 
  ON readings (scope_key, ts_utc DESC) 
  WHERE scope_type = 'station';

CREATE INDEX IF NOT EXISTS idx_readings_ingested 
  ON readings (ingested_at DESC);

-- Compound indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_readings_city_pollutant 
  ON readings (scope_type, scope_key, ts_utc) 
  WHERE pm25 IS NOT NULL OR pm10 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_readings_qc_ok 
  ON readings (scope_type, scope_key, ts_utc) 
  WHERE qc_state = 'OK';

-- TimescaleDB compression policy (compress data older than 7 days)
ALTER TABLE readings SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'scope_type,scope_key',
  timescaledb.compress_orderby = 'ts_utc DESC'
);

SELECT add_compression_policy('readings', INTERVAL '7 days', if_not_exists => TRUE);

-- Optional: Retention policy (uncomment to auto-delete old data)
-- SELECT add_retention_policy('readings', INTERVAL '5 years', if_not_exists => TRUE);

-- =============================================================================
-- 5) Forecasts Table
-- =============================================================================

-- Forecast data for cities and stations
CREATE TABLE IF NOT EXISTS forecasts (
  -- Scope identification
  scope_type      scope_type NOT NULL,      -- 'city' | 'station'
  scope_key       TEXT NOT NULL,            -- same as readings table
  kind            forecast_kind NOT NULL,   -- 'hourly' | 'daily'
  ts_target       TIMESTAMPTZ NOT NULL,     -- forecasted timestamp
  
  -- Forecast horizon metadata
  forecast_hour   SMALLINT,                 -- hours ahead from issue time
  issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  -- Air quality forecasts
  aqi_us          SMALLINT,
  aqi_cn          SMALLINT,
  pm25            DOUBLE PRECISION,
  pm10            DOUBLE PRECISION,
  o3              DOUBLE PRECISION,
  no2             DOUBLE PRECISION,
  so2             DOUBLE PRECISION,
  co              DOUBLE PRECISION,
  
  -- Weather forecasts
  temp_c          DOUBLE PRECISION,
  temp_min_c      DOUBLE PRECISION,         -- daily min temperature
  temp_max_c      DOUBLE PRECISION,         -- daily max temperature
  humidity        DOUBLE PRECISION,
  pressure_hpa    DOUBLE PRECISION,
  wind_speed_ms   DOUBLE PRECISION,
  wind_dir_deg    INTEGER,
  weather_icon    TEXT,
  weather_desc    TEXT,                     -- textual description
  heatindex_c     DOUBLE PRECISION,
  uv_index        DOUBLE PRECISION,
  pop_pct         SMALLINT,                 -- probability of precipitation
  precip_mm       DOUBLE PRECISION,         -- expected precipitation
  
  -- Metadata
  units           JSONB,                    -- units for this forecast
  confidence      DOUBLE PRECISION,         -- forecast confidence (0-1)
  source          TEXT NOT NULL DEFAULT 'airvisual',
  raw             JSONB,                    -- raw forecast data
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  PRIMARY KEY (scope_type, scope_key, kind, ts_target)
);

-- Convert to hypertable
SELECT create_hypertable('forecasts', by_range('ts_target'), if_not_exists => TRUE);

-- Forecast indexes
CREATE INDEX IF NOT EXISTS idx_forecasts_city_hourly
  ON forecasts (scope_key, ts_target DESC) 
  WHERE scope_type = 'city' AND kind = 'hourly';

CREATE INDEX IF NOT EXISTS idx_forecasts_city_daily
  ON forecasts (scope_key, ts_target DESC) 
  WHERE scope_type = 'city' AND kind = 'daily';

CREATE INDEX IF NOT EXISTS idx_forecasts_station_hourly
  ON forecasts (scope_key, ts_target DESC) 
  WHERE scope_type = 'station' AND kind = 'hourly';

CREATE INDEX IF NOT EXISTS idx_forecasts_issued
  ON forecasts (issued_at DESC);

-- Forecast retention (keep forecasts for 90 days)
SELECT add_retention_policy('forecasts', INTERVAL '90 days', if_not_exists => TRUE);

-- =============================================================================
-- 6) Continuous Aggregates for Rollups
-- =============================================================================

-- Daily rollups for cities (used by history API with rollups)
CREATE MATERIALIZED VIEW IF NOT EXISTS ca_daily_city
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', r.ts_utc, 'UTC') AS day_utc,
  r.scope_key,
  
  -- AQI statistics (using explicit type casts for round function)
  ROUND(avg(r.aqi_us)::numeric)::integer AS aqi_us_mean,
  max(r.aqi_us) AS aqi_us_max,
  min(r.aqi_us) AS aqi_us_min,
  ROUND(avg(r.aqi_cn)::numeric)::integer AS aqi_cn_mean,
  max(r.aqi_cn) AS aqi_cn_max,
  min(r.aqi_cn) AS aqi_cn_min,
  
  -- PM2.5 statistics
  ROUND(avg(r.pm25)::numeric, 1)::double precision AS pm25_mean,
  ROUND(max(r.pm25)::numeric, 1)::double precision AS pm25_max,
  ROUND(min(r.pm25)::numeric, 1)::double precision AS pm25_min,
  
  -- PM10 statistics
  ROUND(avg(r.pm10)::numeric, 1)::double precision AS pm10_mean,
  ROUND(max(r.pm10)::numeric, 1)::double precision AS pm10_max,
  ROUND(min(r.pm10)::numeric, 1)::double precision AS pm10_min,
  
  -- Temperature statistics
  ROUND(avg(r.temp_c)::numeric, 1)::double precision AS temp_mean,
  ROUND(max(r.temp_c)::numeric, 1)::double precision AS temp_max,
  ROUND(min(r.temp_c)::numeric, 1)::double precision AS temp_min,
  
  -- Data quality
  count(*) AS hours_total,
  count(*) FILTER (WHERE r.qc_state = 'OK') AS hours_valid,
  count(*) FILTER (WHERE r.pm25 IS NOT NULL) AS hours_pm25,
  
  -- Metadata
  max(r.ingested_at) AS last_updated
FROM readings r
WHERE r.scope_type = 'city'
GROUP BY r.scope_key, day_utc
WITH NO DATA;

-- Continuous aggregate policy
SELECT add_continuous_aggregate_policy('ca_daily_city',
  start_offset => INTERVAL '32 days',
  end_offset   => INTERVAL '2 hours',
  schedule_interval => INTERVAL '1 hour',
  if_not_exists => TRUE
);

-- Weekly rollups for longer-term trends
CREATE MATERIALIZED VIEW IF NOT EXISTS ca_weekly_city
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 week', r.ts_utc, 'UTC') AS week_utc,
  r.scope_key,
  ROUND(avg(r.aqi_us)::numeric)::integer AS aqi_us_mean,
  ROUND(avg(r.pm25)::numeric, 1)::double precision AS pm25_mean,
  count(*) AS hours_total
FROM readings r
WHERE r.scope_type = 'city'
GROUP BY r.scope_key, week_utc
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ca_weekly_city',
  start_offset => INTERVAL '8 weeks',
  end_offset   => INTERVAL '1 day',
  schedule_interval => INTERVAL '6 hours',
  if_not_exists => TRUE
);

-- =============================================================================
-- 7) Caching Tables (Optional DB-backed cache)
-- =============================================================================

-- Simple key-value cache for API responses
CREATE TABLE IF NOT EXISTS cache_blobs (
  cache_key       TEXT PRIMARY KEY,         -- structured cache key
  payload         JSONB NOT NULL,           -- cached response data
  content_type    TEXT DEFAULT 'application/json',
  stored_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  expire_at       TIMESTAMPTZ NOT NULL,
  access_count    INTEGER DEFAULT 0,
  last_accessed   TIMESTAMPTZ DEFAULT now()
);

-- Cache cleanup index
CREATE INDEX IF NOT EXISTS idx_cache_expire ON cache_blobs (expire_at);
CREATE INDEX IF NOT EXISTS idx_cache_accessed ON cache_blobs (last_accessed);

-- =============================================================================
-- 8) Metadata and Configuration Tables
-- =============================================================================

-- Pollutant unit definitions
CREATE TABLE IF NOT EXISTS units_catalog (
  pollutant       pollutant_code PRIMARY KEY,
  default_unit    TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  description     TEXT
);

INSERT INTO units_catalog (pollutant, default_unit, display_name, description) VALUES
  ('pm25', 'µg/m³', 'PM2.5', 'Fine particulate matter'),
  ('pm10', 'µg/m³', 'PM10', 'Coarse particulate matter'),
  ('o3', 'ppb', 'Ozone', 'Ground-level ozone'),
  ('no2', 'ppb', 'NO₂', 'Nitrogen dioxide'),
  ('so2', 'ppb', 'SO₂', 'Sulfur dioxide'),
  ('co', 'ppm', 'CO', 'Carbon monoxide')
ON CONFLICT (pollutant) DO NOTHING;

-- AQI breakpoints for calculation
CREATE TABLE IF NOT EXISTS aqi_breakpoints (
  scale           TEXT NOT NULL,            -- 'us' | 'cn'
  pollutant       pollutant_code NOT NULL,
  idx             SMALLINT NOT NULL,        -- breakpoint index
  conc_lo         DOUBLE PRECISION NOT NULL, -- concentration low
  conc_hi         DOUBLE PRECISION NOT NULL, -- concentration high
  aqi_lo          SMALLINT NOT NULL,        -- AQI low
  aqi_hi          SMALLINT NOT NULL,        -- AQI high
  category        TEXT NOT NULL,            -- 'Good', 'Moderate', etc.
  color           TEXT,                     -- hex color for UI
  PRIMARY KEY (scale, pollutant, idx)
);

-- US EPA AQI breakpoints for PM2.5 (example - add others as needed)
INSERT INTO aqi_breakpoints (scale, pollutant, idx, conc_lo, conc_hi, aqi_lo, aqi_hi, category, color) VALUES
  ('us', 'pm25', 1, 0.0, 12.0, 0, 50, 'Good', '#00e400'),
  ('us', 'pm25', 2, 12.1, 35.4, 51, 100, 'Moderate', '#ffff00'),
  ('us', 'pm25', 3, 35.5, 55.4, 101, 150, 'Unhealthy for Sensitive Groups', '#ff7e00'),
  ('us', 'pm25', 4, 55.5, 150.4, 151, 200, 'Unhealthy', '#ff0000'),
  ('us', 'pm25', 5, 150.5, 250.4, 201, 300, 'Very Unhealthy', '#8f3f97'),
  ('us', 'pm25', 6, 250.5, 500.4, 301, 500, 'Hazardous', '#7e0023')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 9) Utility Functions
-- =============================================================================

-- Function to generate station IDs (SHA1 hash of identifying attributes)
CREATE OR REPLACE FUNCTION generate_station_id(
  p_country TEXT,
  p_state TEXT,
  p_city TEXT,
  p_name TEXT,
  p_lat DOUBLE PRECISION,
  p_lon DOUBLE PRECISION
) RETURNS CHAR(16) AS $$
BEGIN
  RETURN substring(
    encode(
      digest(
        format('%s|%s|%s|%s|%.6f|%.6f', p_country, p_state, p_city, p_name, p_lat, p_lon),
        'sha1'
      ),
      'hex'
    ),
    1, 16
  );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to get the latest reading for a scope
CREATE OR REPLACE FUNCTION get_latest_reading(
  p_scope_type scope_type,
  p_scope_key TEXT
) RETURNS SETOF readings AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM readings r
  WHERE r.scope_type = p_scope_type 
    AND r.scope_key = p_scope_key
  ORDER BY r.ts_utc DESC
  LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 10) Views for API Convenience
-- =============================================================================

-- Latest readings per city with geographic data
CREATE VIEW v_current_cities AS
SELECT DISTINCT ON (r.scope_key)
  r.scope_key,
  c.name AS city_name,
  s.name AS state_name,
  co.name AS country_name,
  ST_X(ST_Centroid(c.centroid::geometry)) AS lon,
  ST_Y(ST_Centroid(c.centroid::geometry)) AS lat,
  r.ts_utc,
  r.aqi_us,
  r.aqi_cn,
  r.pm25,
  r.pm10,
  r.temp_c,
  r.humidity,
  r.qc_state
FROM readings r
JOIN cities c ON c.scope_key = r.scope_key
LEFT JOIN states s ON s.id = c.state_id
JOIN countries co ON co.id = c.country_id
WHERE r.scope_type = 'city'
ORDER BY r.scope_key, r.ts_utc DESC;

-- Latest readings per station with geographic data
CREATE VIEW v_current_stations AS
SELECT DISTINCT ON (r.scope_key)
  r.scope_key AS station_id,
  st.name AS station_name,
  c.name AS city_name,
  s.name AS state_name,
  co.name AS country_name,
  st.lat,
  st.lon,
  r.ts_utc,
  r.aqi_us,
  r.aqi_cn,
  r.pm25,
  r.pm10,
  r.temp_c,
  r.humidity,
  r.qc_state
FROM readings r
JOIN stations st ON st.station_id = r.scope_key
LEFT JOIN cities c ON c.id = st.city_id
LEFT JOIN states s ON s.id = st.state_id
JOIN countries co ON co.id = st.country_id
WHERE r.scope_type = 'station'
ORDER BY r.scope_key, r.ts_utc DESC;

-- =============================================================================
-- 11) Initial Data and Cleanup
-- =============================================================================

-- Cleanup function to remove expired cache entries
CREATE OR REPLACE FUNCTION cleanup_expired_cache() RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM cache_blobs WHERE expire_at < now();
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Schema Complete - Fixed Version
-- =============================================================================