-- 006_ops_station_fetch_health.sql — per-station view of hourly IQAir fetch health.
--
-- Apply manually (never auto-run by the application):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/006_ops_station_fetch_health.sql
--
-- Idempotent. Creates ONLY a view in the `ops` schema; nothing in `public` is touched.
-- Needs 001 (ops.ingest_runs, ops.ingest_run_entities).
--
-- What it answers: which stations fail the hourly /station fetch, how often over
-- the last 24 ingest-stations runs, whether discovery still lists them
-- (stations.last_seen_at) and when they last produced a reading. A station with
-- fails_24 >= 20 and a recent last_discovered is an IQAir-side inconsistency
-- (listed on /stations, refused on /station) to raise with the provider; one
-- with an old last_discovered is simply gone and will be aged out by discovery.

BEGIN;

CREATE OR REPLACE VIEW ops.v_station_fetch_health AS
WITH last_runs AS (
    SELECT run_id
      FROM ops.ingest_runs
     WHERE task = 'ingest-stations'
     ORDER BY started_at DESC
     LIMIT 24
),
fails AS (
    SELECT e.entity_key                              AS station_id,
           count(*)                                  AS fails_24,
           max(e.error_class)                        AS last_error_class,
           max(e.run_id)                             AS last_failed_run
      FROM ops.ingest_run_entities e
      JOIN last_runs r ON r.run_id = e.run_id
     WHERE e.entity_type = 'station' AND e.outcome = 'failed'
     GROUP BY e.entity_key
)
SELECT st.station_id,
       st.name,
       p.code                                        AS provider_code,
       co.name                                       AS country,
       s.name                                        AS state,
       c.name                                        AS city,
       st.active,
       st.last_seen_at                               AS last_discovered,
       f.fails_24,
       f.last_error_class,
       f.last_failed_run,
       (SELECT max(rd.ts_utc)
          FROM public.readings rd
         WHERE rd.scope_type = 'station' AND rd.scope_key = st.station_id
           AND rd.ts_utc > now() - interval '30 days') AS last_reading_30d,
       CASE
         WHEN f.fails_24 >= 20 AND st.last_seen_at > now() - interval '7 days' THEN 'provider_refuses_listed_station'
         WHEN f.fails_24 >= 20                                                  THEN 'gone_from_provider'
         WHEN f.fails_24 >= 6                                                   THEN 'intermittent'
         ELSE 'ok'
       END                                           AS verdict
  FROM fails f
  JOIN public.stations st ON st.station_id = f.station_id
  LEFT JOIN public.providers p ON p.id = st.provider_id
  LEFT JOIN public.countries co ON co.id = st.country_id
  LEFT JOIN public.states s ON s.id = st.state_id
  LEFT JOIN public.cities c ON c.id = st.city_id;

COMMENT ON VIEW ops.v_station_fetch_health IS
  'Stations that failed the hourly IQAir /station fetch in the last 24 ingest-stations runs, with discovery liveness and last reading.';

-- GRANT SELECT ON ops.v_station_fetch_health TO <app_role>;

COMMIT;
