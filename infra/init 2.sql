-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS postgis CASCADE;

-- Create monitor_sources table
CREATE TABLE monitor_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('iqair','openaq','local'))
);

-- Create cities table
CREATE TABLE cities (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    geom geometry(Polygon, 4326)
);

-- Create stations table
CREATE TABLE stations (
    id BIGSERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES monitor_sources(id),
    external_id TEXT,
    name TEXT NOT NULL,
    city_id BIGINT REFERENCES cities(id),
    geom geometry(Point, 4326) NOT NULL,
    meta_json JSONB
);

-- Create spatial index
CREATE INDEX stations_geom_gix ON stations USING gist (geom);

-- Create readings table
CREATE TABLE readings (
    station_id BIGINT REFERENCES stations(id),
    ts TIMESTAMPTZ NOT NULL,
    pm25 REAL,
    pm10 REAL,
    o3 REAL,
    no2 REAL,
    so2 REAL,
    co REAL,
    temp REAL,
    hum REAL,
    aqi_raw REAL,
    qc_state TEXT CHECK (qc_state IN ('OK','SUSPECT','BAD','BACKFILLED')),
    origin TEXT CHECK (origin IN ('minute','hour','backfill')),
    payload_json JSONB,
    PRIMARY KEY (station_id, ts)
);

-- Create hypertable for readings
SELECT create_hypertable('readings', by_range('ts'), if_not_exists => TRUE);


-- Create continuous aggregates
CREATE MATERIALIZED VIEW agg_hour
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS bucket,
       station_id,
       avg(pm25) AS pm25_avg,
       avg(pm10) AS pm10_avg,
       avg(aqi_raw) AS aqi_avg,
       count(*) AS readings_count
FROM readings
GROUP BY bucket, station_id;

CREATE MATERIALIZED VIEW agg_day
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS bucket,
       station_id,
       avg(pm25) AS pm25_avg,
       avg(pm10) AS pm10_avg,
       avg(aqi_raw) AS aqi_avg,
       count(*) AS readings_count
FROM agg_hour
GROUP BY bucket, station_id;

-- Insert sample data
INSERT INTO monitor_sources (name, type) VALUES 
    ('IQAir', 'iqair'),
    ('OpenAQ', 'openaq'),
    ('Local Sensors', 'local');

INSERT INTO cities (name, country, geom) VALUES 
    ('Karachi', 'Pakistan', ST_GeomFromText('POLYGON((66.8 24.7, 67.6 24.7, 67.6 25.2, 66.8 25.2, 66.8 24.7))', 4326)),
    ('Lahore', 'Pakistan', ST_GeomFromText('POLYGON((74.0 31.3, 74.8 31.3, 74.8 31.8, 74.0 31.8, 74.0 31.3))', 4326));

-- Insert sample stations
INSERT INTO stations (source_id, external_id, name, city_id, geom) VALUES 
    (1, 'pak-karachi-1', 'Karachi Central', 1, ST_GeomFromText('POINT(67.0011 24.8607)', 4326)),
    (1, 'pak-lahore-1', 'Lahore Central', 2, ST_GeomFromText('POINT(74.3587 31.5204)', 4326));