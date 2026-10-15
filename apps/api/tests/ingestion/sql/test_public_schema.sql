-- Minimal stand-in for public.readings (columns and PK exactly as in db_schema/initial_schema.sql,
-- without TimescaleDB/PostGIS). Used only by the optional real-Postgres tests.
DO $$ BEGIN
    CREATE TYPE public.scope_type AS ENUM ('city', 'station');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE public.pollutant_code AS ENUM ('pm25', 'pm10', 'o3', 'no2', 'so2', 'co');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS public.readings (
    scope_type public.scope_type NOT NULL,
    scope_key text NOT NULL,
    ts_utc timestamp with time zone NOT NULL,
    aqi_us smallint,
    aqi_cn smallint,
    main_us public.pollutant_code,
    main_cn public.pollutant_code,
    pm25 double precision,
    pm10 double precision,
    o3 double precision,
    no2 double precision,
    so2 double precision,
    co double precision,
    units_pm25 text DEFAULT 'µg/m³'::text,
    units_pm10 text DEFAULT 'µg/m³'::text,
    units_o3 text,
    units_no2 text,
    units_so2 text,
    units_co text,
    temp_c double precision,
    humidity double precision,
    pressure_hpa double precision,
    wind_speed_ms double precision,
    wind_dir_deg integer,
    weather_icon text,
    heatindex_c double precision,
    dewpoint_c double precision,
    visibility_km double precision,
    uv_index double precision,
    pop_pct smallint,
    qc_state text,
    qc_flags text[],
    source text DEFAULT 'airvisual'::text NOT NULL,
    raw jsonb,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (scope_type, scope_key, ts_utc)
);
