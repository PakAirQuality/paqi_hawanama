-- 004_copilot_usage.sql
--
-- Daily usage counters for the public analyst-desk copilot (paid Gemini calls).
-- One row per UTC day and scope; scopes are 'global' and 'ip:<address>'.
-- The API refuses a request when the day's counters for either scope are at their
-- configured limit (COPILOT_IP_DAILY_LIMIT, COPILOT_GLOBAL_DAILY_REQUESTS,
-- COPILOT_GLOBAL_DAILY_TOKENS). Additive; touches only the ops schema.
--
-- Apply by hand with psql (same role as 001-003):
--   psql "$DBURL" -v ON_ERROR_STOP=1 -f db_schema/migrations/004_copilot_usage.sql

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.copilot_usage (
    day               date        NOT NULL,
    scope             text        NOT NULL,
    requests          integer     NOT NULL DEFAULT 0,
    prompt_tokens     bigint      NOT NULL DEFAULT 0,
    completion_tokens bigint      NOT NULL DEFAULT 0,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, scope)
);

COMMENT ON TABLE ops.copilot_usage IS
  'Per-day request and token counters for the public copilot; scope = global or ip:<addr>.';

-- Old rows are not needed for enforcement; prune anything older than 60 days when convenient:
--   DELETE FROM ops.copilot_usage WHERE day < current_date - 60;
