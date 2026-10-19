-- 2026-10_export_membership.sql
--
-- Export membership used to be inferred from providers.display_name = 'Airvisual/PAQI',
-- a label nothing in the code sets and discovery once overwrote. The export routes now
-- require stations.metadata_json.export.openaq = true. This marks the current network.
--
-- STEP 1 (read-only): who would be marked? Inspect the counts before step 2.
SELECT p.code, p.display_name, co.iso2, count(*) AS stations
FROM stations s
JOIN providers p  ON p.id = s.provider_id
JOIN countries co ON co.id = s.country_id
WHERE p.display_name = 'Airvisual/PAQI' AND s.active
GROUP BY 1, 2, 3;

-- If the display_name was already clobbered to 'Airvisual' (step 1 returns nothing),
-- use the fallback predicate in step 2 instead:
--   WHERE p.code = 'airvisual' AND co.iso2 = 'PK' AND s.active
-- and double-check the count matches the expected network size (~210).

-- STEP 2 (idempotent, additive; wrapped in a transaction — COMMIT only after re-checking).
BEGIN;

UPDATE stations s
   SET metadata_json = COALESCE(s.metadata_json, '{}'::jsonb)
       || jsonb_build_object('export', jsonb_build_object(
              'openaq', true,
              'network', 'PAQI',
              'since', now()::date::text,
              'set_by', 'oneoff_2026-10_export_membership'))
  FROM providers p
 WHERE p.id = s.provider_id
   AND p.display_name = 'Airvisual/PAQI'
   AND s.active
   AND COALESCE((s.metadata_json->'export'->>'openaq')::boolean, false) IS NOT TRUE;

-- Expect ≈ the network size. If it is 0 or wildly off, ROLLBACK and revisit step 1.
SELECT count(*) AS exportable FROM stations WHERE (metadata_json->'export'->>'openaq')::boolean IS TRUE;

-- COMMIT;   -- or ROLLBACK;

-- STEP 3 (optional, cosmetic): restore the provider label. Membership no longer depends on it.
-- UPDATE providers SET display_name = 'Airvisual/PAQI' WHERE code = 'airvisual' AND display_name = 'Airvisual';

-- To remove a station from the export later (reversible):
-- UPDATE stations SET metadata_json = metadata_json || '{"export": {"openaq": false}}'::jsonb WHERE station_id = '<id>';
