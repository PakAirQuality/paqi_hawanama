-- 001_ops_ingestion.sql — operational state for ingestion (PR 1).
--
-- Apply manually (never auto-run by the application):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/001_ops_ingestion.sql
--
-- Idempotent. Creates ONLY the new `ops` schema and its tables. No table,
-- column, enum, index or constraint in `public` is touched. The application
-- tolerates these tables being absent (it logs and continues) except for
-- ops.provider_quota on the ingest role, where it fails the run visibly
-- rather than run unmetered.
--
-- 002_ops_provenance.sql (PR 2) and 003_openaq_streams.sql (PR 3) build on this.

BEGIN;

CREATE SCHEMA IF NOT EXISTS ops;

-- One row per task invocation (Cloud Scheduler hit, manual HTTP call, or CLI run).
CREATE TABLE IF NOT EXISTS ops.ingest_runs (
    run_id                 text        PRIMARY KEY,
    task                   text        NOT NULL,   -- 'discover' | 'ingest-stations' | 'ingest-cities' | 'full-pipeline' | 'punjab-ingest' | 'openaq-*'
    provider_code          text        NOT NULL,   -- 'airvisual' | 'punjab' | 'openaq' | ...
    scope                  text        NOT NULL DEFAULT 'all',   -- country filter or 'all'
    trigger                text        NOT NULL,   -- 'scheduler' | 'http' | 'cli'
    status                 text        NOT NULL CHECK (status IN ('running','success','partial','failed','skipped')),
    started_at             timestamptz NOT NULL DEFAULT now(),
    finished_at            timestamptz,
    duration_ms            integer,
    expected_count         integer     NOT NULL DEFAULT 0,   -- inventory targeted after filters
    attempted_count        integer     NOT NULL DEFAULT 0,
    completed_count        integer     NOT NULL DEFAULT 0,
    failed_count           integer     NOT NULL DEFAULT 0,
    rows_fetched           integer     NOT NULL DEFAULT 0,   -- rows parsed from provider responses (pre-dedupe)
    rows_written           integer     NOT NULL DEFAULT 0,   -- rows inserted or updated in readings
    rows_unchanged         integer     NOT NULL DEFAULT 0,   -- rows already present / no-op
    latest_observation_ts  timestamptz,
    observation_lag_s      integer,
    manifest_source        text,       -- 'gcs' | 'local' | 'derived' | 'db'
    manifest_generation    text,       -- GCS object generation (text: avoids bigint/JSON issues)
    manifest_rows          integer,
    lease_key              text,
    lease_fence            bigint,
    error_class            text,       -- 'empty_inventory' | 'quota_unavailable' | 'provider_auth' | 'lease_held' | exception class name
    error_message          text,
    git_sha                text,
    provenance             text,
    host                   text,       -- K_REVISION or hostname, plus pid
    details                jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ingest_runs_task_started_idx   ON ops.ingest_runs (task, started_at DESC);
CREATE INDEX IF NOT EXISTS ingest_runs_status_started_idx ON ops.ingest_runs (status, started_at DESC);

-- Per-entity outcome (failures always; completions optionally) for a run.
CREATE TABLE IF NOT EXISTS ops.ingest_run_entities (
    run_id         text     NOT NULL REFERENCES ops.ingest_runs(run_id) ON DELETE CASCADE,
    entity_type    text     NOT NULL,   -- 'station' | 'city' | 'state' | 'country' | 'stream'
    entity_key     text     NOT NULL,   -- station_id / scope_key / 'country|state' / stream_key
    outcome        text     NOT NULL CHECK (outcome IN ('completed','failed','skipped')),
    error_class    text,
    error_message  text,
    attempts       smallint NOT NULL DEFAULT 1,
    rows_written   integer  NOT NULL DEFAULT 0,
    details        jsonb,
    PRIMARY KEY (run_id, entity_type, entity_key)
);
CREATE INDEX IF NOT EXISTS ingest_run_entities_failed_idx
    ON ops.ingest_run_entities (entity_type, entity_key) WHERE outcome = 'failed';

-- Shared, atomic request budget per provider credential. One row per (alias, window).
-- Reservation is a single row-locked statement:
--   INSERT ... ON CONFLICT DO UPDATE SET used = used + 1 WHERE used < quota_limit RETURNING ...
-- so concurrent instances cannot exceed quota_limit within a window.
CREATE TABLE IF NOT EXISTS ops.provider_quota (
    credential_alias text        NOT NULL,   -- e.g. 'iqair-prod', 'openaq-prod'
    window_kind      text        NOT NULL CHECK (window_kind IN ('minute','hour','day','month')),
    window_start     timestamptz NOT NULL,
    used             integer     NOT NULL DEFAULT 0 CHECK (used >= 0),
    quota_limit      integer     NOT NULL CHECK (quota_limit > 0),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (credential_alias, window_kind, window_start)
);
CREATE INDEX IF NOT EXISTS provider_quota_window_start_idx ON ops.provider_quota (window_start);

-- Mutual exclusion for scheduled work across Cloud Run instances / scheduler retries.
-- fence increments on every (re)acquisition so a stale holder cannot renew or release.
CREATE TABLE IF NOT EXISTS ops.ingest_leases (
    lease_key    text        PRIMARY KEY,   -- e.g. 'ingest-stations:airvisual:all'
    holder       text        NOT NULL,
    acquired_at  timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    fence        bigint      NOT NULL DEFAULT 1
);

-- If the application connects as a role other than the owner of this schema,
-- uncomment and fill in the role before applying:
-- GRANT USAGE ON SCHEMA ops TO <app_role>;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO <app_role>;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO <app_role>;

COMMIT;
