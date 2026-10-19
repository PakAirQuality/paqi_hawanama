-- 003_openaq_streams.sql — OpenAQ stream checkpoints and the alias-aware coverage view (PR 3).
--
-- Apply manually after 001 and 002:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/003_openaq_streams.sql
--
-- Idempotent; only the `ops` schema. OpenAQ stations are ordinary rows in public.stations
-- (provider code 'openaq', active=false, metadata_json.ingest_mode='shadow') and their
-- readings are ordinary rows in public.readings (source='openaq'); nothing in `public` changes.

BEGIN;

CREATE SCHEMA IF NOT EXISTS ops;

-- One row per (sensor, parameter) stream. completed_through is the end of the last window
-- whose pages were ALL durably written; NULL means never completed.
CREATE TABLE IF NOT EXISTS ops.stream_checkpoints (
    provider             text        NOT NULL,                 -- 'openaq'
    stream_key           text        NOT NULL,                 -- 'sensor:<sensor_id>:<parameter>'
    station_id           char(16)    NOT NULL,                 -- public.stations.station_id (no FK: ops stays decoupled)
    native_location_id   text        NOT NULL,
    native_sensor_id     text        NOT NULL,
    parameter            text        NOT NULL,                 -- 'pm25'
    product              text        NOT NULL DEFAULT 'measurements',   -- 'measurements' | 'hours'
    units_reported       text,
    interval_observed    text,                                 -- period.interval from the first page seen (e.g. '01:00:00')
    status               text        NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','deferred_subhourly','excluded_loop','excluded_mobile','retired','failed')),
    completed_through    timestamptz,
    overlap_hours        integer     NOT NULL DEFAULT 72,
    reconciled_through   timestamptz,
    last_reconcile_at    timestamptz,
    last_run_id          text,
    last_attempt_at      timestamptz,
    last_success_at      timestamptz,
    last_page_count      integer,
    last_row_count       integer,
    last_error           text,                                 -- redacted message only
    consecutive_failures integer     NOT NULL DEFAULT 0,
    missed_runs          integer     NOT NULL DEFAULT 0,       -- discovery runs that did not list this sensor
    first_seen_at        timestamptz NOT NULL DEFAULT now(),
    last_seen_at         timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, stream_key)
);
CREATE INDEX IF NOT EXISTS stream_checkpoints_sched_idx
    ON ops.stream_checkpoints (provider, status, completed_through NULLS FIRST, last_attempt_at NULLS FIRST);
CREATE INDEX IF NOT EXISTS stream_checkpoints_station_idx ON ops.stream_checkpoints (station_id);

-- Coverage view: two station rows joined by a reviewed `same_device` alias in
-- stations.metadata_json.identity.aliases count once. Alias candidates written by
-- discovery (reviewed=false) do not collapse anything.
CREATE OR REPLACE VIEW ops.v_station_canonical AS
SELECT s.station_id,
       COALESCE(
         (SELECT (a->>'station_id')::char(16)
            FROM jsonb_array_elements(COALESCE(s.metadata_json->'identity'->'aliases', '[]'::jsonb)) a
           WHERE a->>'relation' = 'same_device' AND (a->>'reviewed')::boolean IS TRUE
           ORDER BY a->>'station_id' LIMIT 1),
         s.station_id) AS canonical_station_id,
       s.provider_id,
       s.active,
       s.metadata_json->>'ingest_mode' AS ingest_mode,
       s.metadata_json->>'origin'      AS origin
FROM public.stations s;

COMMIT;
