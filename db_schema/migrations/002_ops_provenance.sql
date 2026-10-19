-- 002_ops_provenance.sql — raw payload index and reading revisions (PR 2).
--
-- Apply manually after 001:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/002_ops_provenance.sql
--
-- Idempotent. Only the `ops` schema is touched. Raw payload BODIES live in
-- GCS (gzip JSON, credentials stripped); this table is the index that links
-- a normalized reading (readings.raw.prov.sha) back to the object it came from.

BEGIN;

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.raw_payloads (
    payload_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    provider            text        NOT NULL,            -- 'airvisual' | 'punjab' | 'bam' | 'openaq'
    stream              text        NOT NULL,            -- 'station' | 'city' | 'stations' | 'station_24h' | 'measurements' | ...
    native_id           text        NOT NULL,            -- provider-native identifier (source_station_id, city scope_key, sensor id)
    request_window_from timestamptz,
    request_window_to   timestamptz,
    fetched_at          timestamptz NOT NULL,
    sha256              char(64)    NOT NULL,            -- over the canonical JSON of the payload only
    gcs_uri             text,                            -- NULL when archive failed or is disabled
    archived            boolean     NOT NULL DEFAULT false,
    archive_error       text,
    parser_version      text        NOT NULL,
    run_id              text,                            -- no FK: a payload must be indexable even if the run row failed to record
    http_status         smallint,
    size_bytes          integer,
    request_meta        jsonb,                           -- redacted endpoint/params
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_payloads_provider_native_fetched_idx ON ops.raw_payloads (provider, native_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS raw_payloads_sha256_idx ON ops.raw_payloads (sha256);
CREATE INDEX IF NOT EXISTS raw_payloads_run_idx ON ops.raw_payloads (run_id);

-- One row per field whose stored value was changed (or withdrawn) by a later
-- payload. Kept out of readings.raw so hypertable tuples do not grow on every
-- revision and cross-row questions ("what changed in run X") stay cheap.
CREATE TABLE IF NOT EXISTS ops.reading_revisions (
    revision_id     bigserial   PRIMARY KEY,
    scope_type      text        NOT NULL,                -- text on purpose: ops never references public enums
    scope_key       text        NOT NULL,
    ts_utc          timestamptz NOT NULL,
    field           text        NOT NULL,
    old_value       jsonb,
    new_value       jsonb,                               -- NULL with reason='withdrawn'
    reason          text        NOT NULL DEFAULT 'revised' CHECK (reason IN ('revised','withdrawn')),
    source          text        NOT NULL,
    payload_sha256  char(64),
    run_id          text,                                -- no FK: revisions must never be lost because run accounting degraded
    recorded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reading_revisions_key_idx ON ops.reading_revisions (scope_type, scope_key, ts_utc);
CREATE INDEX IF NOT EXISTS reading_revisions_recorded_idx ON ops.reading_revisions (recorded_at DESC);

-- GRANTs: see 001_ops_ingestion.sql (ALTER DEFAULT PRIVILEGES there covers these tables
-- when applied before this file; otherwise repeat the GRANT for ops.raw_payloads and ops.reading_revisions).

COMMIT;
