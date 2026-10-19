-- 2026-10_registry_status.sql
--
-- Station registry flags from scripts/station_registry_audit.py (run 2026-10-17, Pakistan,
-- 800 active stations). Reversible, additive: only stations.metadata_json->'registry' is
-- written; the public schema is untouched. The API hides registry.status = 'test' from
-- /meta/stations, /dashboard/stations and /reports/*; 'retired' is informational until
-- the deactivation policy is decided.
--
-- STEP 1 (read-only): confirm the rows before writing.
SELECT s.station_id, s.name, p.code AS provider, c.name AS city, st.name AS state,
       (SELECT max(ts_utc) FROM readings r WHERE r.scope_type = 'station' AND r.scope_key = s.station_id) AS last_reading
FROM stations s
LEFT JOIN providers p ON p.id = s.provider_id
LEFT JOIN cities c ON c.id = s.city_id
LEFT JOIN states st ON st.id = s.state_id
WHERE s.station_id IN ('4efcde94ea3e7ce1')      -- "Test Device", airvisual-paqi, Lahore
   OR (p.code = 'other' AND s.active AND s.name <> btrim(s.name));   -- trailing-space duplicates under provider "other"

-- STEP 2 (transaction; COMMIT only after STEP 1 looks right).
BEGIN;

-- 2a. The one explicit test device: hidden from every public list.
UPDATE stations s
   SET metadata_json = COALESCE(s.metadata_json, '{}'::jsonb)
       || jsonb_build_object('registry', jsonb_build_object(
              'status', 'test',
              'reason', 'name "Test Device"; audit 2026-10-17',
              'set_by', 'oneoff_2026-10_registry_status',
              'since', now()::date::text))
 WHERE s.station_id = '4efcde94ea3e7ce1';

-- 2b (PROPOSAL, review before running): duplicate registrations under provider "other"
-- whose name only differs by a trailing space from a station that still reports, and that
-- have no reading in 30 days (e.g. "Quetta Commissioner Office " attached to Punjab).
-- Marks them 'retired' with the id of the live twin; nothing is deactivated.
-- UPDATE stations s
--    SET metadata_json = COALESCE(s.metadata_json, '{}'::jsonb)
--        || jsonb_build_object('registry', jsonb_build_object(
--               'status', 'retired', 'duplicate_of', live.station_id,
--               'reason', 'trailing-space duplicate under provider other; no reading in 30 d; audit 2026-10-17',
--               'set_by', 'oneoff_2026-10_registry_status', 'since', now()::date::text))
--   FROM providers p, stations live
--  WHERE p.id = s.provider_id AND p.code = 'other' AND s.active
--    AND s.name <> btrim(s.name)
--    AND live.station_id <> s.station_id AND live.active AND btrim(live.name) = btrim(s.name)
--    AND NOT EXISTS (SELECT 1 FROM readings r WHERE r.scope_type = 'station' AND r.scope_key = s.station_id AND r.ts_utc > now() - interval '30 days');

SELECT count(*) AS flagged FROM stations WHERE metadata_json->'registry'->>'status' IS NOT NULL;

-- COMMIT;   -- or ROLLBACK;

-- To undo for one station:
-- UPDATE stations SET metadata_json = metadata_json - 'registry' WHERE station_id = '<id>';
