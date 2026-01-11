--
-- PostgreSQL database dump
--

\restrict UEWKXYyyP8epepAiXD8dXexMUZ51zPD8eIQrfCQKbtH33u1TwTq0Es6wqdEvOBK

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


--
-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


--
-- Name: aqi; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA aqi;


--
-- Name: timescaledb_toolkit; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit WITH SCHEMA public;


--
-- Name: EXTENSION timescaledb_toolkit; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION timescaledb_toolkit IS 'Library of analytical hyperfunctions, time-series pipelining, and other SQL utilities';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: forecast_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.forecast_kind AS ENUM (
    'hourly',
    'daily'
);


--
-- Name: pollutant_code; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.pollutant_code AS ENUM (
    'pm25',
    'pm10',
    'o3',
    'no2',
    'so2',
    'co'
);


--
-- Name: scope_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scope_type AS ENUM (
    'city',
    'station'
);


--
-- Name: cleanup_expired_cache(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cleanup_expired_cache() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM cache_blobs WHERE expire_at < now();
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;


--
-- Name: generate_station_id(text, text, text, text, double precision, double precision); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.generate_station_id(p_country text, p_state text, p_city text, p_name text, p_lat double precision, p_lon double precision) RETURNS character
    LANGUAGE plpgsql IMMUTABLE
    AS $$
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
$$;


--
-- Name: update_city_scope_key(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_city_scope_key() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.scope_key := lower(
    coalesce((SELECT c.name FROM countries c WHERE c.id = NEW.country_id),'') || '|' ||
    coalesce((SELECT s.name FROM states s WHERE s.id = NEW.state_id),'') || '|' ||
    NEW.name
  );
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: _compressed_hypertable_2; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._compressed_hypertable_2 (
);


--
-- Name: readings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.readings (
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
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: _hyper_1_1_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_1_chunk (
    CONSTRAINT constraint_1 CHECK (((ts_utc >= '2025-09-25 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-10-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_2_chunk (
    CONSTRAINT constraint_2 CHECK (((ts_utc >= '2025-10-02 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-10-09 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_3_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_3_chunk (
    CONSTRAINT constraint_3 CHECK (((ts_utc >= '2025-10-09 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-10-16 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_4_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_4_chunk (
    CONSTRAINT constraint_4 CHECK (((ts_utc >= '2025-10-16 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-10-23 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_5_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_5_chunk (
    CONSTRAINT constraint_5 CHECK (((ts_utc >= '2025-10-23 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-10-30 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_6_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_6_chunk (
    CONSTRAINT constraint_6 CHECK (((ts_utc >= '2025-10-30 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-11-06 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_7_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_7_chunk (
    CONSTRAINT constraint_7 CHECK (((ts_utc >= '2025-11-06 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-11-13 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_8_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_8_chunk (
    CONSTRAINT constraint_8 CHECK (((ts_utc >= '2025-11-13 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-11-20 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _hyper_1_9_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_9_chunk (
    CONSTRAINT constraint_9 CHECK (((ts_utc >= '2025-11-20 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-11-27 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- Name: _materialized_hypertable_4; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_4 (
    day_utc timestamp with time zone NOT NULL,
    scope_key text,
    aqi_us_mean integer,
    aqi_us_max smallint,
    aqi_us_min smallint,
    aqi_cn_mean integer,
    aqi_cn_max smallint,
    aqi_cn_min smallint,
    pm25_mean double precision,
    pm25_max double precision,
    pm25_min double precision,
    pm10_mean double precision,
    pm10_max double precision,
    pm10_min double precision,
    temp_mean double precision,
    temp_max double precision,
    temp_min double precision,
    hours_total bigint,
    hours_valid bigint,
    hours_pm25 bigint,
    last_updated timestamp with time zone
);


--
-- Name: _hyper_4_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_4_2_chunk (
    CONSTRAINT constraint_2 CHECK (((day_utc >= '2025-07-31 00:00:00+00'::timestamp with time zone) AND (day_utc < '2025-10-09 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_4);


--
-- Name: _materialized_hypertable_5; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_5 (
    week_utc timestamp with time zone NOT NULL,
    scope_key text,
    aqi_us_mean integer,
    pm25_mean double precision,
    hours_total bigint
);


--
-- Name: readings_stage; Type: TABLE; Schema: aqi; Owner: -
--

CREATE TABLE aqi.readings_stage (
    source_station_id text NOT NULL,
    ts_utc timestamp with time zone NOT NULL,
    pm25 double precision,
    pm10 double precision,
    no2 double precision,
    so2 double precision,
    co double precision,
    o3 double precision,
    aqi_us integer,
    main_us text,
    raw jsonb
);


--
-- Name: stations_stage; Type: TABLE; Schema: aqi; Owner: -
--

CREATE TABLE aqi.stations_stage (
    source_station_id text NOT NULL,
    name text,
    lat double precision,
    lon double precision,
    active boolean
);


--
-- Name: aqi_breakpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aqi_breakpoints (
    scale text NOT NULL,
    pollutant public.pollutant_code NOT NULL,
    idx smallint NOT NULL,
    conc_lo double precision NOT NULL,
    conc_hi double precision NOT NULL,
    aqi_lo smallint NOT NULL,
    aqi_hi smallint NOT NULL,
    category text NOT NULL,
    color text
);


--
-- Name: ca_daily_city; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.ca_daily_city AS
 SELECT day_utc,
    scope_key,
    aqi_us_mean,
    aqi_us_max,
    aqi_us_min,
    aqi_cn_mean,
    aqi_cn_max,
    aqi_cn_min,
    pm25_mean,
    pm25_max,
    pm25_min,
    pm10_mean,
    pm10_max,
    pm10_min,
    temp_mean,
    temp_max,
    temp_min,
    hours_total,
    hours_valid,
    hours_pm25,
    last_updated
   FROM _timescaledb_internal._materialized_hypertable_4;


--
-- Name: ca_weekly_city; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.ca_weekly_city AS
 SELECT week_utc,
    scope_key,
    aqi_us_mean,
    pm25_mean,
    hours_total
   FROM _timescaledb_internal._materialized_hypertable_5;


--
-- Name: cities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cities (
    id bigint NOT NULL,
    country_id bigint NOT NULL,
    state_id bigint,
    name text NOT NULL,
    geom public.geography(MultiPolygon,4326),
    centroid public.geography(Point,4326),
    population bigint,
    timezone text,
    active boolean DEFAULT true NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    scope_key text
);


--
-- Name: cities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cities_id_seq OWNED BY public.cities.id;


--
-- Name: countries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.countries (
    id bigint NOT NULL,
    name text NOT NULL,
    iso2 character(2),
    iso3 character(3),
    geom public.geography(MultiPolygon,4326),
    centroid public.geography(Point,4326),
    population bigint,
    active boolean DEFAULT true NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: countries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.countries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: countries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.countries_id_seq OWNED BY public.countries.id;


--
-- Name: providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.providers (
    id smallint NOT NULL,
    code text NOT NULL,
    display_name text NOT NULL,
    api_url text,
    metadata jsonb,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.providers_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.providers_id_seq OWNED BY public.providers.id;


--
-- Name: sa_daily_station; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.sa_daily_station AS
 SELECT public.time_bucket('1 day'::interval, ts_utc, 'UTC'::text) AS day_utc,
    scope_key AS station_id,
    avg(pm25) AS pm25_mean,
    count(*) AS hours_total,
    count(*) FILTER (WHERE (qc_state = 'OK'::text)) AS hours_qc_ok
   FROM public.readings
  WHERE (scope_type = 'station'::public.scope_type)
  GROUP BY scope_key, (public.time_bucket('1 day'::interval, ts_utc, 'UTC'::text));


--
-- Name: states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.states (
    id bigint NOT NULL,
    country_id bigint NOT NULL,
    name text NOT NULL,
    code text,
    geom public.geography(MultiPolygon,4326),
    centroid public.geography(Point,4326),
    population bigint,
    active boolean DEFAULT true NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: states_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.states_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: states_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.states_id_seq OWNED BY public.states.id;


--
-- Name: station_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.station_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stations (
    station_id character(16) NOT NULL,
    country_id bigint NOT NULL,
    state_id bigint,
    city_id bigint,
    name text NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    geom public.geography(Point,4326) GENERATED ALWAYS AS ((public.st_setsrid(public.st_makepoint(lon, lat), 4326))::public.geography) STORED,
    provider_id smallint NOT NULL,
    source_station_id text,
    elevation_m double precision,
    metadata_json jsonb,
    timezone text,
    active boolean DEFAULT true NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    monitor_type text
);


--
-- Name: units_catalog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.units_catalog (
    pollutant public.pollutant_code NOT NULL,
    default_unit text NOT NULL,
    display_name text NOT NULL,
    description text
);


--
-- Name: _hyper_1_1_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_1_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_1_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_1_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_2_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_2_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_2_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_2_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_2_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_2_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_2_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_2_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_3_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_3_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_3_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_3_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_4_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_4_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_4_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_4_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_4_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_4_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_4_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_4_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_5_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_5_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_5_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_5_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_5_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_5_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_5_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_5_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_6_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_6_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_6_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_6_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_7_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_7_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_7_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_7_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_7_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_7_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_7_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_7_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_8_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_8_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_8_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_8_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_8_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_8_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_8_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_8_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: _hyper_1_9_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_9_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_9_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_9_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- Name: _hyper_1_9_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_9_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- Name: _hyper_1_9_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_9_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- Name: cities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities ALTER COLUMN id SET DEFAULT nextval('public.cities_id_seq'::regclass);


--
-- Name: countries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries ALTER COLUMN id SET DEFAULT nextval('public.countries_id_seq'::regclass);


--
-- Name: providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers ALTER COLUMN id SET DEFAULT nextval('public.providers_id_seq'::regclass);


--
-- Name: states id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states ALTER COLUMN id SET DEFAULT nextval('public.states_id_seq'::regclass);


--
-- Name: _hyper_1_1_chunk 1_1_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk
    ADD CONSTRAINT "1_1_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_2_chunk 2_2_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_2_chunk
    ADD CONSTRAINT "2_2_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_3_chunk 3_3_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk
    ADD CONSTRAINT "3_3_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_4_chunk 4_4_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_4_chunk
    ADD CONSTRAINT "4_4_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_5_chunk 5_5_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_5_chunk
    ADD CONSTRAINT "5_5_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_6_chunk 6_6_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk
    ADD CONSTRAINT "6_6_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_7_chunk 7_7_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_7_chunk
    ADD CONSTRAINT "7_7_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_8_chunk 8_8_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_8_chunk
    ADD CONSTRAINT "8_8_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: _hyper_1_9_chunk 9_9_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_9_chunk
    ADD CONSTRAINT "9_9_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: readings_stage readings_stage_pkey; Type: CONSTRAINT; Schema: aqi; Owner: -
--

ALTER TABLE ONLY aqi.readings_stage
    ADD CONSTRAINT readings_stage_pkey PRIMARY KEY (source_station_id, ts_utc);


--
-- Name: stations_stage stations_stage_pkey; Type: CONSTRAINT; Schema: aqi; Owner: -
--

ALTER TABLE ONLY aqi.stations_stage
    ADD CONSTRAINT stations_stage_pkey PRIMARY KEY (source_station_id);


--
-- Name: aqi_breakpoints aqi_breakpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aqi_breakpoints
    ADD CONSTRAINT aqi_breakpoints_pkey PRIMARY KEY (scale, pollutant, idx);


--
-- Name: cities cities_country_id_state_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_country_id_state_id_name_key UNIQUE (country_id, state_id, name);


--
-- Name: cities cities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_pkey PRIMARY KEY (id);


--
-- Name: countries countries_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries
    ADD CONSTRAINT countries_name_key UNIQUE (name);


--
-- Name: countries countries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries
    ADD CONSTRAINT countries_pkey PRIMARY KEY (id);


--
-- Name: providers providers_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_code_key UNIQUE (code);


--
-- Name: providers providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_pkey PRIMARY KEY (id);


--
-- Name: readings readings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readings
    ADD CONSTRAINT readings_pkey PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- Name: states states_country_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT states_country_id_name_key UNIQUE (country_id, name);


--
-- Name: states states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT states_pkey PRIMARY KEY (id);


--
-- Name: stations stations_country_id_state_id_city_id_name_lat_lon_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_country_id_state_id_city_id_name_lat_lon_key UNIQUE (country_id, state_id, city_id, name, lat, lon);


--
-- Name: stations stations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_pkey PRIMARY KEY (station_id);


--
-- Name: stations stations_provider_id_source_station_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_provider_id_source_station_id_key UNIQUE (provider_id, source_station_id);


--
-- Name: units_catalog units_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.units_catalog
    ADD CONSTRAINT units_catalog_pkey PRIMARY KEY (pollutant);


--
-- Name: city_hourly_from_stations; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.city_hourly_from_stations
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', r.ts_utc, 'UTC') AS hour_utc,
  s.city_id,
  AVG(r.pm25) FILTER (
      WHERE r.pm25 IS NOT NULL
        AND (r.qc_state IS NULL OR r.qc_state != 'INVALID')
  ) AS pm25_mean,
  AVG(r.aqi_us) FILTER (
      WHERE r.aqi_us IS NOT NULL
        AND (r.qc_state IS NULL OR r.qc_state != 'INVALID')
  ) AS aqi_mean,
  COUNT(*) FILTER (
      WHERE r.pm25 IS NOT NULL
        AND (r.qc_state IS NULL OR r.qc_state != 'INVALID')
  ) AS sample_count,
  COUNT(DISTINCT r.scope_key) FILTER (
      WHERE r.pm25 IS NOT NULL
        AND (r.qc_state IS NULL OR r.qc_state != 'INVALID')
  ) AS station_count
FROM readings r
JOIN stations s
  ON r.scope_type = 'station'
 AND r.scope_key = s.station_id
GROUP BY hour_utc, s.city_id;

--
-- Name: city_hourly_from_stations_city_id_hour_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX city_hourly_from_stations_city_id_hour_utc_idx ON public.city_hourly_from_stations USING btree (city_id, hour_utc DESC);

--
-- Name: city_hourly_from_stations; Type: CONTINUOUS AGGREGATE POLICY; Schema: public; Owner: -
--

SELECT add_continuous_aggregate_policy('public.city_hourly_from_stations', start_offset => INTERVAL '5 years', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes');


--
-- Name: _hyper_1_1_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_1_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_1_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_1_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_1_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_1_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_1_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_1_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_2_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_2_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_2_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_2_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_2_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_2_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_2_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_2_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_2_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_2_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_2_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_2_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_2_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_2_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_2_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_2_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_2_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_2_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_3_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_3_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_3_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_3_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_3_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_3_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_3_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_3_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_3_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_3_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_3_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_3_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_4_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_4_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_4_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_4_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_4_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_4_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_4_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_4_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_4_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_4_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_4_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_4_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_4_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_4_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_4_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_4_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_4_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_4_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_5_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_5_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_5_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_5_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_5_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_5_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_5_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_5_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_5_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_5_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_5_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_5_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_5_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_5_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_5_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_5_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_5_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_5_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_6_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_6_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_6_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_6_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_6_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_6_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_6_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_6_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_6_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_6_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_6_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_6_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_7_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_7_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_7_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_7_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_7_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_7_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_7_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_7_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_7_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_7_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_7_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_7_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_8_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_8_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_8_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_8_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_8_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_8_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_8_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_8_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_8_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_8_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_8_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_8_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_8_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_8_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_8_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_8_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_8_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_8_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_1_9_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_9_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_9_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: _hyper_1_9_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_9_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_9_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: _hyper_1_9_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_9_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_9_chunk USING btree (ingested_at DESC);


--
-- Name: _hyper_1_9_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_9_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_9_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: _hyper_1_9_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_9_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_9_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: _hyper_1_9_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_9_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_9_chunk USING btree (ts_utc DESC);


--
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_day_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_day_utc_idx ON _timescaledb_internal._hyper_4_2_chunk USING btree (day_utc DESC);


--
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_scope_key_day_utc_i; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_scope_key_day_utc_i ON _timescaledb_internal._hyper_4_2_chunk USING btree (scope_key, day_utc DESC);


--
-- Name: _materialized_hypertable_4_day_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_4_day_utc_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (day_utc DESC);


--
-- Name: _materialized_hypertable_4_scope_key_day_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_4_scope_key_day_utc_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (scope_key, day_utc DESC);


--
-- Name: _materialized_hypertable_5_scope_key_week_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_5_scope_key_week_utc_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (scope_key, week_utc DESC);


--
-- Name: _materialized_hypertable_5_week_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_5_week_utc_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (week_utc DESC);


--
-- Name: idx_cities_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_centroid ON public.cities USING gist (centroid);


--
-- Name: idx_cities_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_country ON public.cities USING btree (country_id);


--
-- Name: idx_cities_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_geom ON public.cities USING gist (geom);


--
-- Name: idx_cities_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_name_trgm ON public.cities USING gin (name public.gin_trgm_ops);


--
-- Name: idx_cities_scopekey; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_scopekey ON public.cities USING btree (scope_key);


--
-- Name: idx_cities_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_state ON public.cities USING btree (state_id);


--
-- Name: idx_countries_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_countries_centroid ON public.countries USING gist (centroid);


--
-- Name: idx_countries_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_countries_geom ON public.countries USING gist (geom);


--
-- Name: idx_countries_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_countries_name_trgm ON public.countries USING gin (name public.gin_trgm_ops);


--
-- Name: idx_readings_city_pollutant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_city_pollutant ON public.readings USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- Name: idx_readings_city_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_city_recent ON public.readings USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- Name: idx_readings_ingested; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_ingested ON public.readings USING btree (ingested_at DESC);


--
-- Name: idx_readings_qc_ok; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_qc_ok ON public.readings USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- Name: idx_readings_station_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_station_recent ON public.readings USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- Name: idx_states_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_centroid ON public.states USING gist (centroid);


--
-- Name: idx_states_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_country ON public.states USING btree (country_id);


--
-- Name: idx_states_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_geom ON public.states USING gist (geom);


--
-- Name: idx_states_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_name_trgm ON public.states USING gin (name public.gin_trgm_ops);


--
-- Name: idx_stations_city; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_city ON public.stations USING btree (city_id);


--
-- Name: idx_stations_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_geom ON public.stations USING gist (geom);


--
-- Name: idx_stations_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_name_trgm ON public.stations USING gin (name public.gin_trgm_ops);


--
-- Name: idx_stations_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_provider ON public.stations USING btree (provider_id);


--
-- Name: readings_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX readings_ts_utc_idx ON public.readings USING btree (ts_utc DESC);


--
-- Name: _compressed_hypertable_2 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._compressed_hypertable_2 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_4 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_4 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_5 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_5 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: cities trigger_update_city_scope_key; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_city_scope_key BEFORE INSERT OR UPDATE ON public.cities FOR EACH ROW EXECUTE FUNCTION public.update_city_scope_key();


--
-- Name: readings ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.readings FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: cities cities_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.countries(id) ON DELETE CASCADE;


--
-- Name: cities cities_state_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_state_id_fkey FOREIGN KEY (state_id) REFERENCES public.states(id) ON DELETE CASCADE;


--
-- Name: states states_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT states_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.countries(id) ON DELETE CASCADE;


--
-- Name: stations stations_city_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_city_id_fkey FOREIGN KEY (city_id) REFERENCES public.cities(id) ON DELETE SET NULL;


--
-- Name: stations stations_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.countries(id) ON DELETE RESTRICT;


--
-- Name: stations stations_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id) ON DELETE RESTRICT;


--
-- Name: stations stations_state_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_state_id_fkey FOREIGN KEY (state_id) REFERENCES public.states(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict UEWKXYyyP8epepAiXD8dXexMUZ51zPD8eIQrfCQKbtH33u1TwTq0Es6wqdEvOBK

