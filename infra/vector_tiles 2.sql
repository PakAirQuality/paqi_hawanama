-- Vector tile views for pg_tileserv
-- These views will be automatically served as MVT tiles at /stations and /grid_hour

-- 1. Station points layer with latest readings and QC state
CREATE OR REPLACE VIEW stations_vt AS
SELECT 
    s.id,
    s.name,
    s.external_id,
    s.geom,
    -- Latest reading data
    r.aqi_raw,
    r.pm25,
    r.pm10,
    r.temp,
    r.hum,
    r.qc_state,
    r.ts as last_reading,
    -- AQI category for styling
    CASE 
        WHEN r.aqi_raw IS NULL THEN 'no_data'
        WHEN r.aqi_raw <= 50 THEN 'good'
        WHEN r.aqi_raw <= 100 THEN 'moderate'
        WHEN r.aqi_raw <= 150 THEN 'unhealthy_sensitive'
        WHEN r.aqi_raw <= 200 THEN 'unhealthy'
        WHEN r.aqi_raw <= 300 THEN 'very_unhealthy'
        ELSE 'hazardous'
    END as aqi_category,
    -- QC flag for styling
    CASE 
        WHEN r.qc_state = 'OK' THEN 'good'
        WHEN r.qc_state = 'SUSPECT' THEN 'suspect'
        WHEN r.qc_state = 'BAD' THEN 'bad'
        ELSE 'unknown'
    END as qc_flag,
    -- Time since last update (for staleness indication)
    EXTRACT(EPOCH FROM (NOW() - r.ts))/3600 as hours_since_update
FROM stations s
LEFT JOIN LATERAL (
    SELECT aqi_raw, pm25, pm10, temp, hum, qc_state, ts
    FROM readings_minute rm 
    WHERE rm.station_id = s.id 
    ORDER BY rm.ts DESC 
    LIMIT 1
) r ON true
WHERE s.geom IS NOT NULL;

-- Add comments for pg_tileserv metadata
COMMENT ON VIEW stations_vt IS 'Station points with latest air quality readings and QC status';
COMMENT ON COLUMN stations_vt.id IS 'Unique station identifier';
COMMENT ON COLUMN stations_vt.name IS 'Station display name';
COMMENT ON COLUMN stations_vt.aqi_raw IS 'Latest AQI reading';
COMMENT ON COLUMN stations_vt.aqi_category IS 'AQI category: good, moderate, unhealthy_sensitive, unhealthy, very_unhealthy, hazardous';
COMMENT ON COLUMN stations_vt.qc_flag IS 'Data quality: good, suspect, bad, unknown';
COMMENT ON COLUMN stations_vt.hours_since_update IS 'Hours since last reading (for staleness detection)';

-- 2. Hourly grid aggregation (2km grid cells)
CREATE OR REPLACE VIEW grid_hour_vt AS
WITH grid_bounds AS (
    -- Get bounds of all stations to create appropriate grid
    SELECT 
        ST_XMin(ST_Extent(geom)) as xmin,
        ST_YMin(ST_Extent(geom)) as ymin,
        ST_XMax(ST_Extent(geom)) as xmax,
        ST_YMax(ST_Extent(geom)) as ymax
    FROM stations
),
grid_cells AS (
    -- Create 2km grid cells (approximately 0.02 degrees)
    SELECT 
        row_number() OVER () as grid_id,
        ST_MakeEnvelope(
            x, y, 
            x + 0.02, y + 0.02, 
            4326
        ) as geom,
        x, y
    FROM grid_bounds,
         generate_series(
             grid_bounds.xmin::numeric, 
             grid_bounds.xmax::numeric, 
             0.02
         ) as x,
         generate_series(
             grid_bounds.ymin::numeric, 
             grid_bounds.ymax::numeric, 
             0.02
         ) as y
),
grid_with_data AS (
    SELECT 
        gc.grid_id,
        gc.geom,
        -- Aggregate readings from last hour for stations in this grid cell
        AVG(ah.pm25_avg) as pm25_avg,
        AVG(ah.aqi_avg) as aqi_avg,
        COUNT(ah.station_id) as station_count,
        MAX(ah.bucket) as latest_hour
    FROM grid_cells gc
    LEFT JOIN stations s ON ST_Within(s.geom, gc.geom)
    LEFT JOIN agg_hour ah ON ah.station_id = s.id 
        AND ah.bucket >= date_trunc('hour', NOW() - interval '1 hour')
    GROUP BY gc.grid_id, gc.geom
    HAVING COUNT(ah.station_id) > 0  -- Only show grid cells with data
)
SELECT 
    grid_id,
    geom,
    pm25_avg,
    aqi_avg,
    station_count,
    latest_hour,
    -- AQI category for grid cell styling
    CASE 
        WHEN aqi_avg IS NULL THEN 'no_data'
        WHEN aqi_avg <= 50 THEN 'good'
        WHEN aqi_avg <= 100 THEN 'moderate'
        WHEN aqi_avg <= 150 THEN 'unhealthy_sensitive'
        WHEN aqi_avg <= 200 THEN 'unhealthy'
        WHEN aqi_avg <= 300 THEN 'very_unhealthy'
        ELSE 'hazardous'
    END as aqi_category,
    -- Data freshness
    EXTRACT(EPOCH FROM (NOW() - latest_hour))/3600 as hours_old
FROM grid_with_data
WHERE aqi_avg IS NOT NULL;

COMMENT ON VIEW grid_hour_vt IS 'Hourly aggregated AQI data on 2km grid for heatmap visualization';
COMMENT ON COLUMN grid_hour_vt.grid_id IS 'Unique grid cell identifier';
COMMENT ON COLUMN grid_hour_vt.pm25_avg IS 'Average PM2.5 in grid cell';
COMMENT ON COLUMN grid_hour_vt.aqi_avg IS 'Average AQI in grid cell';
COMMENT ON COLUMN grid_hour_vt.station_count IS 'Number of stations contributing to this cell';
COMMENT ON COLUMN grid_hour_vt.aqi_category IS 'AQI category for styling';

-- 3. Daily grid aggregation (same structure, different time window)
CREATE OR REPLACE VIEW grid_day_vt AS
WITH grid_bounds AS (
    SELECT 
        ST_XMin(ST_Extent(geom)) as xmin,
        ST_YMin(ST_Extent(geom)) as ymin,
        ST_XMax(ST_Extent(geom)) as xmax,
        ST_YMax(ST_Extent(geom)) as ymax
    FROM stations
),
grid_cells AS (
    SELECT 
        row_number() OVER () as grid_id,
        ST_MakeEnvelope(
            x, y, 
            x + 0.02, y + 0.02, 
            4326
        ) as geom
    FROM grid_bounds,
         generate_series(
             grid_bounds.xmin::numeric, 
             grid_bounds.xmax::numeric, 
             0.02
         ) as x,
         generate_series(
             grid_bounds.ymin::numeric, 
             grid_bounds.ymax::numeric, 
             0.02
         ) as y
),
grid_with_data AS (
    SELECT 
        gc.grid_id,
        gc.geom,
        -- Aggregate readings from last 24 hours
        AVG(ad.pm25_avg) as pm25_avg,
        AVG(ad.aqi_avg) as aqi_avg,
        COUNT(ad.station_id) as station_count,
        MAX(ad.bucket) as latest_day
    FROM grid_cells gc
    LEFT JOIN stations s ON ST_Within(s.geom, gc.geom)
    LEFT JOIN agg_day ad ON ad.station_id = s.id 
        AND ad.bucket >= date_trunc('day', NOW() - interval '1 day')
    GROUP BY gc.grid_id, gc.geom
    HAVING COUNT(ad.station_id) > 0
)
SELECT 
    grid_id,
    geom,
    pm25_avg,
    aqi_avg,
    station_count,
    latest_day,
    CASE 
        WHEN aqi_avg IS NULL THEN 'no_data'
        WHEN aqi_avg <= 50 THEN 'good'
        WHEN aqi_avg <= 100 THEN 'moderate'
        WHEN aqi_avg <= 150 THEN 'unhealthy_sensitive'
        WHEN aqi_avg <= 200 THEN 'unhealthy'
        WHEN aqi_avg <= 300 THEN 'very_unhealthy'
        ELSE 'hazardous'
    END as aqi_category,
    EXTRACT(EPOCH FROM (NOW() - latest_day))/86400 as days_old
FROM grid_with_data
WHERE aqi_avg IS NOT NULL;

COMMENT ON VIEW grid_day_vt IS 'Daily aggregated AQI data on 2km grid for longer-term patterns';

-- Create indexes for better tile serving performance
CREATE INDEX IF NOT EXISTS idx_stations_vt_geom ON stations_vt USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_hour_vt_geom ON grid_hour_vt USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_day_vt_geom ON grid_day_vt USING GIST (geom);