--
-- PostgreSQL database dump
--

\restrict YwNetaKIw93IwXDzXuWf3liuM6zo5AecP4aCjFAefPgKabDg6Xij1nJYxpCKS9h

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6 (Homebrew)

-- Started on 2025-10-28 19:40:39 +04

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
-- TOC entry 2 (class 3079 OID 16463)
-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


--
-- TOC entry 7810 (class 0 OID 0)
-- Dependencies: 2
-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


--
-- TOC entry 6 (class 3079 OID 17255)
-- Name: timescaledb_toolkit; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit WITH SCHEMA public;


--
-- TOC entry 7811 (class 0 OID 0)
-- Dependencies: 6
-- Name: EXTENSION timescaledb_toolkit; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION timescaledb_toolkit IS 'Library of analytical hyperfunctions, time-series pipelining, and other SQL utilities';


--
-- TOC entry 5 (class 3079 OID 18753)
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- TOC entry 7812 (class 0 OID 0)
-- Dependencies: 5
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- TOC entry 4 (class 3079 OID 18834)
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- TOC entry 7813 (class 0 OID 0)
-- Dependencies: 4
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- TOC entry 3 (class 3079 OID 18871)
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- TOC entry 7814 (class 0 OID 0)
-- Dependencies: 3
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- TOC entry 3449 (class 1247 OID 19948)
-- Name: forecast_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.forecast_kind AS ENUM (
    'hourly',
    'daily'
);


--
-- TOC entry 3452 (class 1247 OID 19954)
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
-- TOC entry 3455 (class 1247 OID 19968)
-- Name: scope_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scope_type AS ENUM (
    'city',
    'station'
);


--
-- TOC entry 2426 (class 1255 OID 19973)
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
-- TOC entry 2427 (class 1255 OID 19974)
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 290 (class 1259 OID 19975)
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
-- TOC entry 2428 (class 1255 OID 19984)
-- Name: get_latest_reading(public.scope_type, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_latest_reading(p_scope_type public.scope_type, p_scope_key text) RETURNS SETOF public.readings
    LANGUAGE plpgsql
    AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM readings r
  WHERE r.scope_type = p_scope_type 
    AND r.scope_key = p_scope_key
  ORDER BY r.ts_utc DESC
  LIMIT 1;
END;
$$;


--
-- TOC entry 2429 (class 1255 OID 19985)
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


--
-- TOC entry 291 (class 1259 OID 19986)
-- Name: _compressed_hypertable_2; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._compressed_hypertable_2 (
);


--
-- TOC entry 292 (class 1259 OID 19989)
-- Name: _direct_view_4; Type: VIEW; Schema: _timescaledb_internal; Owner: -
--

CREATE VIEW _timescaledb_internal._direct_view_4 AS
 SELECT public.time_bucket('1 day'::interval, ts_utc, 'UTC'::text) AS day_utc,
    scope_key,
    (round(avg(aqi_us)))::integer AS aqi_us_mean,
    max(aqi_us) AS aqi_us_max,
    min(aqi_us) AS aqi_us_min,
    (round(avg(aqi_cn)))::integer AS aqi_cn_mean,
    max(aqi_cn) AS aqi_cn_max,
    min(aqi_cn) AS aqi_cn_min,
    (round((avg(pm25))::numeric, 1))::double precision AS pm25_mean,
    (round((max(pm25))::numeric, 1))::double precision AS pm25_max,
    (round((min(pm25))::numeric, 1))::double precision AS pm25_min,
    (round((avg(pm10))::numeric, 1))::double precision AS pm10_mean,
    (round((max(pm10))::numeric, 1))::double precision AS pm10_max,
    (round((min(pm10))::numeric, 1))::double precision AS pm10_min,
    (round((avg(temp_c))::numeric, 1))::double precision AS temp_mean,
    (round((max(temp_c))::numeric, 1))::double precision AS temp_max,
    (round((min(temp_c))::numeric, 1))::double precision AS temp_min,
    count(*) AS hours_total,
    count(*) FILTER (WHERE (qc_state = 'OK'::text)) AS hours_valid,
    count(*) FILTER (WHERE (pm25 IS NOT NULL)) AS hours_pm25,
    max(ingested_at) AS last_updated
   FROM public.readings r
  WHERE (scope_type = 'city'::public.scope_type)
  GROUP BY scope_key, (public.time_bucket('1 day'::interval, ts_utc, 'UTC'::text));


--
-- TOC entry 293 (class 1259 OID 19994)
-- Name: _direct_view_5; Type: VIEW; Schema: _timescaledb_internal; Owner: -
--

CREATE VIEW _timescaledb_internal._direct_view_5 AS
 SELECT public.time_bucket('7 days'::interval, ts_utc, 'UTC'::text) AS week_utc,
    scope_key,
    (round(avg(aqi_us)))::integer AS aqi_us_mean,
    (round((avg(pm25))::numeric, 1))::double precision AS pm25_mean,
    count(*) AS hours_total
   FROM public.readings r
  WHERE (scope_type = 'city'::public.scope_type)
  GROUP BY scope_key, (public.time_bucket('7 days'::interval, ts_utc, 'UTC'::text));


--
-- TOC entry 294 (class 1259 OID 19999)
-- Name: _hyper_1_1_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_1_chunk (
    CONSTRAINT constraint_1 CHECK (((ts_utc >= '2025-09-25 00:00:00+00'::timestamp with time zone) AND (ts_utc < '2025-10-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.readings);


--
-- TOC entry 295 (class 1259 OID 20009)
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
-- TOC entry 296 (class 1259 OID 20014)
-- Name: _hyper_4_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_4_2_chunk (
    CONSTRAINT constraint_2 CHECK (((day_utc >= '2025-07-31 00:00:00+00'::timestamp with time zone) AND (day_utc < '2025-10-09 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_4);


--
-- TOC entry 297 (class 1259 OID 20020)
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
-- TOC entry 298 (class 1259 OID 20025)
-- Name: _partial_view_4; Type: VIEW; Schema: _timescaledb_internal; Owner: -
--

CREATE VIEW _timescaledb_internal._partial_view_4 AS
 SELECT public.time_bucket('1 day'::interval, ts_utc, 'UTC'::text) AS day_utc,
    scope_key,
    (round(avg(aqi_us)))::integer AS aqi_us_mean,
    max(aqi_us) AS aqi_us_max,
    min(aqi_us) AS aqi_us_min,
    (round(avg(aqi_cn)))::integer AS aqi_cn_mean,
    max(aqi_cn) AS aqi_cn_max,
    min(aqi_cn) AS aqi_cn_min,
    (round((avg(pm25))::numeric, 1))::double precision AS pm25_mean,
    (round((max(pm25))::numeric, 1))::double precision AS pm25_max,
    (round((min(pm25))::numeric, 1))::double precision AS pm25_min,
    (round((avg(pm10))::numeric, 1))::double precision AS pm10_mean,
    (round((max(pm10))::numeric, 1))::double precision AS pm10_max,
    (round((min(pm10))::numeric, 1))::double precision AS pm10_min,
    (round((avg(temp_c))::numeric, 1))::double precision AS temp_mean,
    (round((max(temp_c))::numeric, 1))::double precision AS temp_max,
    (round((min(temp_c))::numeric, 1))::double precision AS temp_min,
    count(*) AS hours_total,
    count(*) FILTER (WHERE (qc_state = 'OK'::text)) AS hours_valid,
    count(*) FILTER (WHERE (pm25 IS NOT NULL)) AS hours_pm25,
    max(ingested_at) AS last_updated
   FROM public.readings r
  WHERE (scope_type = 'city'::public.scope_type)
  GROUP BY scope_key, (public.time_bucket('1 day'::interval, ts_utc, 'UTC'::text));


--
-- TOC entry 299 (class 1259 OID 20030)
-- Name: _partial_view_5; Type: VIEW; Schema: _timescaledb_internal; Owner: -
--

CREATE VIEW _timescaledb_internal._partial_view_5 AS
 SELECT public.time_bucket('7 days'::interval, ts_utc, 'UTC'::text) AS week_utc,
    scope_key,
    (round(avg(aqi_us)))::integer AS aqi_us_mean,
    (round((avg(pm25))::numeric, 1))::double precision AS pm25_mean,
    count(*) AS hours_total
   FROM public.readings r
  WHERE (scope_type = 'city'::public.scope_type)
  GROUP BY scope_key, (public.time_bucket('7 days'::interval, ts_utc, 'UTC'::text));


--
-- TOC entry 300 (class 1259 OID 20035)
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
-- TOC entry 301 (class 1259 OID 20040)
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
-- TOC entry 302 (class 1259 OID 20045)
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
-- TOC entry 303 (class 1259 OID 20049)
-- Name: cache_blobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cache_blobs (
    cache_key text NOT NULL,
    payload jsonb NOT NULL,
    content_type text DEFAULT 'application/json'::text,
    stored_at timestamp with time zone DEFAULT now() NOT NULL,
    expire_at timestamp with time zone NOT NULL,
    access_count integer DEFAULT 0,
    last_accessed timestamp with time zone DEFAULT now()
);


--
-- TOC entry 304 (class 1259 OID 20058)
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
-- TOC entry 305 (class 1259 OID 20066)
-- Name: cities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 7815 (class 0 OID 0)
-- Dependencies: 305
-- Name: cities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cities_id_seq OWNED BY public.cities.id;


--
-- TOC entry 306 (class 1259 OID 20067)
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
-- TOC entry 307 (class 1259 OID 20075)
-- Name: countries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.countries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 7816 (class 0 OID 0)
-- Dependencies: 307
-- Name: countries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.countries_id_seq OWNED BY public.countries.id;


--
-- TOC entry 308 (class 1259 OID 20076)
-- Name: forecasts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecasts (
    scope_type public.scope_type NOT NULL,
    scope_key text NOT NULL,
    kind public.forecast_kind NOT NULL,
    ts_target timestamp with time zone NOT NULL,
    forecast_hour smallint,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    aqi_us smallint,
    aqi_cn smallint,
    pm25 double precision,
    pm10 double precision,
    o3 double precision,
    no2 double precision,
    so2 double precision,
    co double precision,
    temp_c double precision,
    temp_min_c double precision,
    temp_max_c double precision,
    humidity double precision,
    pressure_hpa double precision,
    wind_speed_ms double precision,
    wind_dir_deg integer,
    weather_icon text,
    weather_desc text,
    heatindex_c double precision,
    uv_index double precision,
    pop_pct smallint,
    precip_mm double precision,
    units jsonb,
    confidence double precision,
    source text DEFAULT 'airvisual'::text NOT NULL,
    raw jsonb,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- TOC entry 309 (class 1259 OID 20084)
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
-- TOC entry 310 (class 1259 OID 20091)
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
-- TOC entry 7817 (class 0 OID 0)
-- Dependencies: 310
-- Name: providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.providers_id_seq OWNED BY public.providers.id;


--
-- TOC entry 311 (class 1259 OID 20092)
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
-- TOC entry 312 (class 1259 OID 20100)
-- Name: states_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.states_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 7818 (class 0 OID 0)
-- Dependencies: 312
-- Name: states_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.states_id_seq OWNED BY public.states.id;


--
-- TOC entry 313 (class 1259 OID 20101)
-- Name: station_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.station_versions (
    id bigint NOT NULL,
    station_id character(16),
    valid_from timestamp with time zone NOT NULL,
    valid_to timestamp with time zone,
    name text,
    lat double precision,
    lon double precision,
    metadata_json jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- TOC entry 314 (class 1259 OID 20107)
-- Name: station_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.station_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 7819 (class 0 OID 0)
-- Dependencies: 314
-- Name: station_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.station_versions_id_seq OWNED BY public.station_versions.id;


--
-- TOC entry 315 (class 1259 OID 20108)
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
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- TOC entry 316 (class 1259 OID 20117)
-- Name: units_catalog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.units_catalog (
    pollutant public.pollutant_code NOT NULL,
    default_unit text NOT NULL,
    display_name text NOT NULL,
    description text
);


--
-- TOC entry 317 (class 1259 OID 20122)
-- Name: v_current_cities; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_current_cities AS
 SELECT DISTINCT ON (r.scope_key) r.scope_key,
    c.name AS city_name,
    s.name AS state_name,
    co.name AS country_name,
    public.st_x(public.st_centroid((c.centroid)::public.geometry)) AS lon,
    public.st_y(public.st_centroid((c.centroid)::public.geometry)) AS lat,
    r.ts_utc,
    r.aqi_us,
    r.aqi_cn,
    r.pm25,
    r.pm10,
    r.temp_c,
    r.humidity,
    r.qc_state
   FROM (((public.readings r
     JOIN public.cities c ON ((c.scope_key = r.scope_key)))
     LEFT JOIN public.states s ON ((s.id = c.state_id)))
     JOIN public.countries co ON ((co.id = c.country_id)))
  WHERE (r.scope_type = 'city'::public.scope_type)
  ORDER BY r.scope_key, r.ts_utc DESC;


--
-- TOC entry 318 (class 1259 OID 20127)
-- Name: v_current_stations; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_current_stations AS
 SELECT DISTINCT ON (r.scope_key) r.scope_key AS station_id,
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
   FROM ((((public.readings r
     JOIN public.stations st ON (((st.station_id)::text = r.scope_key)))
     LEFT JOIN public.cities c ON ((c.id = st.city_id)))
     LEFT JOIN public.states s ON ((s.id = st.state_id)))
     JOIN public.countries co ON ((co.id = st.country_id)))
  WHERE (r.scope_type = 'station'::public.scope_type)
  ORDER BY r.scope_key, r.ts_utc DESC;


--
-- TOC entry 7408 (class 2604 OID 20132)
-- Name: _hyper_1_1_chunk units_pm25; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN units_pm25 SET DEFAULT 'µg/m³'::text;


--
-- TOC entry 7409 (class 2604 OID 20133)
-- Name: _hyper_1_1_chunk units_pm10; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN units_pm10 SET DEFAULT 'µg/m³'::text;


--
-- TOC entry 7410 (class 2604 OID 20134)
-- Name: _hyper_1_1_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN source SET DEFAULT 'airvisual'::text;


--
-- TOC entry 7411 (class 2604 OID 20135)
-- Name: _hyper_1_1_chunk ingested_at; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN ingested_at SET DEFAULT now();


--
-- TOC entry 7416 (class 2604 OID 24387)
-- Name: cities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities ALTER COLUMN id SET DEFAULT nextval('public.cities_id_seq'::regclass);


--
-- TOC entry 7420 (class 2604 OID 24388)
-- Name: countries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries ALTER COLUMN id SET DEFAULT nextval('public.countries_id_seq'::regclass);


--
-- TOC entry 7427 (class 2604 OID 24389)
-- Name: providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers ALTER COLUMN id SET DEFAULT nextval('public.providers_id_seq'::regclass);


--
-- TOC entry 7430 (class 2604 OID 24390)
-- Name: states id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states ALTER COLUMN id SET DEFAULT nextval('public.states_id_seq'::regclass);


--
-- TOC entry 7434 (class 2604 OID 24391)
-- Name: station_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.station_versions ALTER COLUMN id SET DEFAULT nextval('public.station_versions_id_seq'::regclass);


--
-- TOC entry 7538 (class 2606 OID 24250)
-- Name: _hyper_1_1_chunk 1_1_readings_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk
    ADD CONSTRAINT "1_1_readings_pkey" PRIMARY KEY (scope_type, scope_key, ts_utc);


--
-- TOC entry 7560 (class 2606 OID 24252)
-- Name: aqi_breakpoints aqi_breakpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aqi_breakpoints
    ADD CONSTRAINT aqi_breakpoints_pkey PRIMARY KEY (scale, pollutant, idx);


--
-- TOC entry 7562 (class 2606 OID 24254)
-- Name: cache_blobs cache_blobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_blobs
    ADD CONSTRAINT cache_blobs_pkey PRIMARY KEY (cache_key);


--
-- TOC entry 7566 (class 2606 OID 24256)
-- Name: cities cities_country_id_state_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_country_id_state_id_name_key UNIQUE (country_id, state_id, name);


--
-- TOC entry 7568 (class 2606 OID 24258)
-- Name: cities cities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_pkey PRIMARY KEY (id);


--
-- TOC entry 7576 (class 2606 OID 24260)
-- Name: countries countries_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries
    ADD CONSTRAINT countries_name_key UNIQUE (name);


--
-- TOC entry 7578 (class 2606 OID 24262)
-- Name: countries countries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries
    ADD CONSTRAINT countries_pkey PRIMARY KEY (id);


--
-- TOC entry 7588 (class 2606 OID 24264)
-- Name: providers providers_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_code_key UNIQUE (code);


--
-- TOC entry 7590 (class 2606 OID 24266)
-- Name: providers providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_pkey PRIMARY KEY (id);


--
-- TOC entry 7596 (class 2606 OID 24268)
-- Name: states states_country_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT states_country_id_name_key UNIQUE (country_id, name);


--
-- TOC entry 7598 (class 2606 OID 24270)
-- Name: states states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT states_pkey PRIMARY KEY (id);


--
-- TOC entry 7600 (class 2606 OID 24272)
-- Name: station_versions station_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.station_versions
    ADD CONSTRAINT station_versions_pkey PRIMARY KEY (id);


--
-- TOC entry 7606 (class 2606 OID 24274)
-- Name: stations stations_country_id_state_id_city_id_name_lat_lon_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_country_id_state_id_city_id_name_lat_lon_key UNIQUE (country_id, state_id, city_id, name, lat, lon);


--
-- TOC entry 7608 (class 2606 OID 24276)
-- Name: stations stations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_pkey PRIMARY KEY (station_id);


--
-- TOC entry 7610 (class 2606 OID 24278)
-- Name: stations stations_provider_id_source_station_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_provider_id_source_station_id_key UNIQUE (provider_id, source_station_id);


--
-- TOC entry 7612 (class 2606 OID 24280)
-- Name: units_catalog units_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.units_catalog
    ADD CONSTRAINT units_catalog_pkey PRIMARY KEY (pollutant);


--
-- TOC entry 7539 (class 1259 OID 24281)
-- Name: _hyper_1_1_chunk_idx_readings_city_pollutant; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_city_pollutant ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- TOC entry 7540 (class 1259 OID 24312)
-- Name: _hyper_1_1_chunk_idx_readings_city_pollutant_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_city_pollutant_1 ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- TOC entry 7541 (class 1259 OID 24282)
-- Name: _hyper_1_1_chunk_idx_readings_city_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_city_recent ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- TOC entry 7542 (class 1259 OID 24314)
-- Name: _hyper_1_1_chunk_idx_readings_city_recent_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_city_recent_1 ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- TOC entry 7543 (class 1259 OID 24283)
-- Name: _hyper_1_1_chunk_idx_readings_ingested; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_ingested ON _timescaledb_internal._hyper_1_1_chunk USING btree (ingested_at DESC);


--
-- TOC entry 7544 (class 1259 OID 24316)
-- Name: _hyper_1_1_chunk_idx_readings_ingested_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_ingested_1 ON _timescaledb_internal._hyper_1_1_chunk USING btree (ingested_at DESC);


--
-- TOC entry 7545 (class 1259 OID 24284)
-- Name: _hyper_1_1_chunk_idx_readings_qc_ok; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_qc_ok ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- TOC entry 7546 (class 1259 OID 24318)
-- Name: _hyper_1_1_chunk_idx_readings_qc_ok_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_qc_ok_1 ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- TOC entry 7547 (class 1259 OID 24285)
-- Name: _hyper_1_1_chunk_idx_readings_station_recent; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_station_recent ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- TOC entry 7548 (class 1259 OID 24320)
-- Name: _hyper_1_1_chunk_idx_readings_station_recent_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_readings_station_recent_1 ON _timescaledb_internal._hyper_1_1_chunk USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- TOC entry 7549 (class 1259 OID 24286)
-- Name: _hyper_1_1_chunk_readings_ts_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_readings_ts_utc_idx ON _timescaledb_internal._hyper_1_1_chunk USING btree (ts_utc DESC);


--
-- TOC entry 7550 (class 1259 OID 24330)
-- Name: _hyper_1_1_chunk_readings_ts_utc_idx_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_readings_ts_utc_idx_1 ON _timescaledb_internal._hyper_1_1_chunk USING btree (ts_utc DESC);


--
-- TOC entry 7553 (class 1259 OID 24287)
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_day_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_day_utc_idx ON _timescaledb_internal._hyper_4_2_chunk USING btree (day_utc DESC);


--
-- TOC entry 7554 (class 1259 OID 24290)
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_day_utc_idx_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_day_utc_idx_1 ON _timescaledb_internal._hyper_4_2_chunk USING btree (day_utc DESC);


--
-- TOC entry 7555 (class 1259 OID 24292)
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_scope_key_day_utc_1; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_scope_key_day_utc_1 ON _timescaledb_internal._hyper_4_2_chunk USING btree (scope_key, day_utc DESC);


--
-- TOC entry 7556 (class 1259 OID 24288)
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_scope_key_day_utc_i; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_scope_key_day_utc_i ON _timescaledb_internal._hyper_4_2_chunk USING btree (scope_key, day_utc DESC);


--
-- TOC entry 7551 (class 1259 OID 24289)
-- Name: _materialized_hypertable_4_day_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_4_day_utc_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (day_utc DESC);


--
-- TOC entry 7552 (class 1259 OID 24291)
-- Name: _materialized_hypertable_4_scope_key_day_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_4_scope_key_day_utc_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (scope_key, day_utc DESC);


--
-- TOC entry 7557 (class 1259 OID 24293)
-- Name: _materialized_hypertable_5_scope_key_week_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_5_scope_key_week_utc_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (scope_key, week_utc DESC);


--
-- TOC entry 7558 (class 1259 OID 24294)
-- Name: _materialized_hypertable_5_week_utc_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _materialized_hypertable_5_week_utc_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (week_utc DESC);


--
-- TOC entry 7582 (class 1259 OID 24295)
-- Name: forecasts_ts_target_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX forecasts_ts_target_idx ON public.forecasts USING btree (ts_target DESC);


--
-- TOC entry 7563 (class 1259 OID 24296)
-- Name: idx_cache_accessed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_accessed ON public.cache_blobs USING btree (last_accessed);


--
-- TOC entry 7564 (class 1259 OID 24297)
-- Name: idx_cache_expire; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_expire ON public.cache_blobs USING btree (expire_at);


--
-- TOC entry 7569 (class 1259 OID 24298)
-- Name: idx_cities_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_centroid ON public.cities USING gist (centroid);


--
-- TOC entry 7570 (class 1259 OID 24299)
-- Name: idx_cities_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_country ON public.cities USING btree (country_id);


--
-- TOC entry 7571 (class 1259 OID 24300)
-- Name: idx_cities_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_geom ON public.cities USING gist (geom);


--
-- TOC entry 7572 (class 1259 OID 24301)
-- Name: idx_cities_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_name_trgm ON public.cities USING gin (name public.gin_trgm_ops);


--
-- TOC entry 7573 (class 1259 OID 24302)
-- Name: idx_cities_scopekey; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_scopekey ON public.cities USING btree (scope_key);


--
-- TOC entry 7574 (class 1259 OID 24303)
-- Name: idx_cities_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cities_state ON public.cities USING btree (state_id);


--
-- TOC entry 7579 (class 1259 OID 24304)
-- Name: idx_countries_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_countries_centroid ON public.countries USING gist (centroid);


--
-- TOC entry 7580 (class 1259 OID 24305)
-- Name: idx_countries_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_countries_geom ON public.countries USING gist (geom);


--
-- TOC entry 7581 (class 1259 OID 24306)
-- Name: idx_countries_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_countries_name_trgm ON public.countries USING gin (name public.gin_trgm_ops);


--
-- TOC entry 7583 (class 1259 OID 24307)
-- Name: idx_forecasts_city_daily; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forecasts_city_daily ON public.forecasts USING btree (scope_key, ts_target DESC) WHERE ((scope_type = 'city'::public.scope_type) AND (kind = 'daily'::public.forecast_kind));


--
-- TOC entry 7584 (class 1259 OID 24308)
-- Name: idx_forecasts_city_hourly; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forecasts_city_hourly ON public.forecasts USING btree (scope_key, ts_target DESC) WHERE ((scope_type = 'city'::public.scope_type) AND (kind = 'hourly'::public.forecast_kind));


--
-- TOC entry 7585 (class 1259 OID 24309)
-- Name: idx_forecasts_issued; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forecasts_issued ON public.forecasts USING btree (issued_at DESC);


--
-- TOC entry 7586 (class 1259 OID 24310)
-- Name: idx_forecasts_station_hourly; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forecasts_station_hourly ON public.forecasts USING btree (scope_key, ts_target DESC) WHERE ((scope_type = 'station'::public.scope_type) AND (kind = 'hourly'::public.forecast_kind));


--
-- TOC entry 7531 (class 1259 OID 24311)
-- Name: idx_readings_city_pollutant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_city_pollutant ON public.readings USING btree (scope_type, scope_key, ts_utc) WHERE ((pm25 IS NOT NULL) OR (pm10 IS NOT NULL));


--
-- TOC entry 7532 (class 1259 OID 24313)
-- Name: idx_readings_city_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_city_recent ON public.readings USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'city'::public.scope_type);


--
-- TOC entry 7533 (class 1259 OID 24315)
-- Name: idx_readings_ingested; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_ingested ON public.readings USING btree (ingested_at DESC);


--
-- TOC entry 7534 (class 1259 OID 24317)
-- Name: idx_readings_qc_ok; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_qc_ok ON public.readings USING btree (scope_type, scope_key, ts_utc) WHERE (qc_state = 'OK'::text);


--
-- TOC entry 7535 (class 1259 OID 24319)
-- Name: idx_readings_station_recent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_readings_station_recent ON public.readings USING btree (scope_key, ts_utc DESC) WHERE (scope_type = 'station'::public.scope_type);


--
-- TOC entry 7591 (class 1259 OID 24321)
-- Name: idx_states_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_centroid ON public.states USING gist (centroid);


--
-- TOC entry 7592 (class 1259 OID 24322)
-- Name: idx_states_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_country ON public.states USING btree (country_id);


--
-- TOC entry 7593 (class 1259 OID 24323)
-- Name: idx_states_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_geom ON public.states USING gist (geom);


--
-- TOC entry 7594 (class 1259 OID 24324)
-- Name: idx_states_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_states_name_trgm ON public.states USING gin (name public.gin_trgm_ops);


--
-- TOC entry 7601 (class 1259 OID 24325)
-- Name: idx_stations_city; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_city ON public.stations USING btree (city_id);


--
-- TOC entry 7602 (class 1259 OID 24326)
-- Name: idx_stations_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_geom ON public.stations USING gist (geom);


--
-- TOC entry 7603 (class 1259 OID 24327)
-- Name: idx_stations_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_name_trgm ON public.stations USING gin (name public.gin_trgm_ops);


--
-- TOC entry 7604 (class 1259 OID 24328)
-- Name: idx_stations_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stations_provider ON public.stations USING btree (provider_id);


--
-- TOC entry 7536 (class 1259 OID 24329)
-- Name: readings_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX readings_ts_utc_idx ON public.readings USING btree (ts_utc DESC);


--
-- TOC entry 7624 (class 2620 OID 24331)
-- Name: _hyper_1_1_chunk ts_cagg_invalidation_trigger; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_cagg_invalidation_trigger AFTER INSERT OR DELETE OR UPDATE ON _timescaledb_internal._hyper_1_1_chunk FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.continuous_agg_invalidation_trigger('1');


--
-- TOC entry 7623 (class 2620 OID 24332)
-- Name: _compressed_hypertable_2 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._compressed_hypertable_2 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7625 (class 2620 OID 24340)
-- Name: _hyper_1_1_chunk ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._hyper_1_1_chunk FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7627 (class 2620 OID 24334)
-- Name: _hyper_4_2_chunk ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._hyper_4_2_chunk FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7626 (class 2620 OID 24333)
-- Name: _materialized_hypertable_4 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_4 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7628 (class 2620 OID 24335)
-- Name: _materialized_hypertable_5 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_5 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7629 (class 2620 OID 24336)
-- Name: cities trigger_update_city_scope_key; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_city_scope_key BEFORE INSERT OR UPDATE ON public.cities FOR EACH ROW EXECUTE FUNCTION public.update_city_scope_key();


--
-- TOC entry 7621 (class 2620 OID 24337)
-- Name: readings ts_cagg_invalidation_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_cagg_invalidation_trigger AFTER INSERT OR DELETE OR UPDATE ON public.readings FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.continuous_agg_invalidation_trigger('1');


--
-- TOC entry 7630 (class 2620 OID 24338)
-- Name: forecasts ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.forecasts FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7622 (class 2620 OID 24339)
-- Name: readings ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.readings FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- TOC entry 7613 (class 2606 OID 24341)
-- Name: cities cities_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.countries(id) ON DELETE CASCADE;


--
-- TOC entry 7614 (class 2606 OID 24346)
-- Name: cities cities_state_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cities
    ADD CONSTRAINT cities_state_id_fkey FOREIGN KEY (state_id) REFERENCES public.states(id) ON DELETE CASCADE;


--
-- TOC entry 7615 (class 2606 OID 24351)
-- Name: states states_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT states_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.countries(id) ON DELETE CASCADE;


--
-- TOC entry 7616 (class 2606 OID 24356)
-- Name: station_versions station_versions_station_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.station_versions
    ADD CONSTRAINT station_versions_station_id_fkey FOREIGN KEY (station_id) REFERENCES public.stations(station_id) ON DELETE CASCADE;


--
-- TOC entry 7617 (class 2606 OID 24361)
-- Name: stations stations_city_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_city_id_fkey FOREIGN KEY (city_id) REFERENCES public.cities(id) ON DELETE SET NULL;


--
-- TOC entry 7618 (class 2606 OID 24366)
-- Name: stations stations_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.countries(id) ON DELETE RESTRICT;


--
-- TOC entry 7619 (class 2606 OID 24371)
-- Name: stations stations_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id) ON DELETE RESTRICT;


--
-- TOC entry 7620 (class 2606 OID 24376)
-- Name: stations stations_state_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stations
    ADD CONSTRAINT stations_state_id_fkey FOREIGN KEY (state_id) REFERENCES public.states(id) ON DELETE SET NULL;


-- Completed on 2025-10-28 19:40:47 +04

--
-- PostgreSQL database dump complete
--

\unrestrict YwNetaKIw93IwXDzXuWf3liuM6zo5AecP4aCjFAefPgKabDg6Xij1nJYxpCKS9h

