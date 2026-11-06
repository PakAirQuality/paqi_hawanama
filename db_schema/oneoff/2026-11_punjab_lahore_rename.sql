-- 2026-11_punjab_lahore_rename.sql
--
-- Punjab EPA renamed its 13 Lahore stations in late October 2026. The station id is a hash of the
-- EPD name, so the live feed now writes to 13 new ids (created 2026-11-01) and the old ids stopped on
-- 2026-10-25. This one-off makes the new id canonical: it moves the old history onto the new id,
-- retires the old row (active=false, registry.status='retired') and records the alias on both rows.
-- Readings are re-keyed, never changed or deleted. The public schema is untouched.
--
-- Mobile units ("Mobile 1".."Mobile 5") are not fixed. Only the days the unit stood at the new
-- row's site (daily-export coordinates within 300 m) move; other days stay on the retired id.
-- Day list from the 2026-11-04 analysis (gs://hawanama-manifests/raw_payloads/punjab/recovery/analysis_2026-11-04/).
--
-- Rollback: readings moved carry no marker, so keep the STEP 1 counts; to undo, re-key the moved
-- ranges back (fixed stations: everything before 2026-10-31 18:00 UTC on the new id; mobile units:
-- the listed days) and strip registry/identity from both rows.

CREATE TEMP TABLE lahore_pairs (old_id text, new_id text, old_name text, new_name text, mobile boolean);
INSERT INTO lahore_pairs VALUES
  ('pb_8ac82cf97330', 'pb_960665899a96', 'Govt. Teaching Hospital Shahdara-LHR', 'Shahdara', false),
  ('pb_f9ce4673e986', 'pb_679fee414414', 'UET-LHR', 'GT Road', false),
  ('pb_7ec7d21be5ab', 'pb_0d5df3cf09d6', 'PKLI-LHR', 'DHA Phase 6', false),
  ('pb_15024e63a91b', 'pb_138a8229979d', 'FMDRC-LHR', 'Barki Road', false),
  ('pb_a5b5b22a36ce', 'pb_e1533559ec5d', 'Kahna Nau Hospital-LHR', 'Kahna Nau', false),
  ('pb_21fd00357a80', 'pb_7ca659fe020d', 'LWMC-LHR', 'Multan Road', false),
  ('pb_86dbcf4a55a3', 'pb_97cb96070feb', 'Punjab University-LHR', 'Punjab University', false),
  ('pb_94dc6924db51', 'pb_c9d47054110c', 'Safari Park-LHR', 'Safari Park', false),
  ('pb_796a78569a8e', 'pb_ff09e20dbe8e', 'Mobile 1', 'Gulberg III, Lahore', true),
  ('pb_e54efa9ff08f', 'pb_2cb19e8f5cde', 'Mobile 2', 'Lathepur', true),
  ('pb_b6177a038664', 'pb_a1f095031219', 'Mobile 3', 'Wagha Border', true),
  ('pb_17500286189f', 'pb_5b8b5e367614', 'Mobile 4', 'Egerton Road', true),
  ('pb_d6f3fbae3a69', 'pb_ec16cf351094', 'Mobile 5', 'BHU Jandiala Kalsan', true);

CREATE TEMP TABLE mobile_days (old_id text, day_from date, day_to date);  -- inclusive, at the new site
INSERT INTO mobile_days VALUES
  ('pb_796a78569a8e', DATE '2025-12-12', DATE '2026-02-16'),
  ('pb_796a78569a8e', DATE '2026-09-21', DATE '2026-10-31'),
  ('pb_e54efa9ff08f', DATE '2025-10-31', DATE '2026-07-20'),
  ('pb_e54efa9ff08f', DATE '2026-08-14', DATE '2026-10-31'),
  ('pb_b6177a038664', DATE '2025-10-27', DATE '2026-10-31'),
  ('pb_17500286189f', DATE '2025-10-27', DATE '2026-10-31'),
  ('pb_d6f3fbae3a69', DATE '2025-10-27', DATE '2026-10-31');

-- STEP 1 (read-only): pairs, counts and overlap. Overlap must be 0 everywhere.
SELECT p.old_name, p.old_id, p.new_name, p.new_id, p.mobile,
       (SELECT count(*) FROM readings r WHERE r.scope_type='station' AND r.scope_key=p.old_id) AS old_rows,
       (SELECT count(*) FROM readings r WHERE r.scope_type='station' AND r.scope_key=p.new_id) AS new_rows,
       (SELECT count(*) FROM readings a JOIN readings b ON b.scope_type='station' AND b.scope_key=p.new_id AND b.ts_utc=a.ts_utc
         WHERE a.scope_type='station' AND a.scope_key=p.old_id) AS overlap,
       (SELECT count(*) FROM readings r JOIN mobile_days d ON d.old_id=p.old_id AND r.ts_utc::date BETWEEN d.day_from AND d.day_to
         WHERE r.scope_type='station' AND r.scope_key=p.old_id) AS mobile_rows_to_move,
       so.active AS old_active, so.metadata_json->'registry'->>'status' AS old_status
FROM lahore_pairs p
JOIN stations so ON trim(so.station_id)=p.old_id
ORDER BY p.old_name;

-- STEP 2 (transaction; COMMIT only after STEP 1 looks right).
BEGIN;

-- 2a. Fixed stations: the whole history moves.
UPDATE readings r
   SET scope_key = p.new_id
  FROM lahore_pairs p
  JOIN stations so ON trim(so.station_id)=p.old_id
 WHERE r.scope_type='station' AND r.scope_key=p.old_id AND NOT p.mobile
   AND COALESCE(so.metadata_json->'registry'->>'status','') <> 'retired';

-- 2b. Mobile units: only the at-site days move.
UPDATE readings r
   SET scope_key = p.new_id
  FROM lahore_pairs p
  JOIN stations so ON trim(so.station_id)=p.old_id
  JOIN mobile_days d ON d.old_id=p.old_id
 WHERE r.scope_type='station' AND r.scope_key=p.old_id AND p.mobile AND r.ts_utc::date BETWEEN d.day_from AND d.day_to
   AND COALESCE(so.metadata_json->'registry'->>'status','') <> 'retired';

-- 2c. Retire the old rows and record the rename.
UPDATE stations s
   SET active = false,
       updated_at = now(),
       metadata_json = COALESCE(s.metadata_json, '{}'::jsonb)
         || jsonb_build_object('registry', jsonb_build_object(
                'status', 'retired', 'duplicate_of', p.new_id,
                'reason', 'EPD renamed the station (' || p.old_name || ' -> ' || p.new_name || ') in Oct 2026; history moved to the new id'
                          || CASE WHEN p.mobile THEN ' for the days the unit stood at that site' ELSE '' END,
                'set_by', 'oneoff_2026-11_punjab_lahore_rename', 'since', now()::date::text))
         || jsonb_build_object('identity', COALESCE(s.metadata_json->'identity', '{}'::jsonb)
              || jsonb_build_object('history', COALESCE(s.metadata_json->'identity'->'history', '[]'::jsonb)
                   || jsonb_build_array(jsonb_build_object(
                        'at', now(), 'event', 'rename_or_move', 'set_by', 'oneoff_2026-11_punjab_lahore_rename',
                        'from', jsonb_build_object('name', p.old_name, 'station_id', p.old_id),
                        'to', jsonb_build_object('name', p.new_name, 'station_id', p.new_id),
                        'readings_kept_here', (SELECT count(*) FROM readings r WHERE r.scope_type='station' AND r.scope_key=p.old_id)))))
  FROM lahore_pairs p
 WHERE trim(s.station_id)=p.old_id
   AND COALESCE(s.metadata_json->'registry'->>'status','') <> 'retired';

-- 2d. Alias on the new rows (reviewed by the operator on 2026-11-04).
UPDATE stations s
   SET updated_at = now(),
       metadata_json = COALESCE(s.metadata_json, '{}'::jsonb)
         || jsonb_build_object('identity', COALESCE(s.metadata_json->'identity', '{}'::jsonb)
              || jsonb_build_object('aliases', COALESCE(s.metadata_json->'identity'->'aliases', '[]'::jsonb)
                   || jsonb_build_array(jsonb_build_object(
                        'station_id', p.old_id, 'provider', 'punjab', 'relation', 'same_device', 'confidence', 1.0,
                        'evidence', 'identical coordinates; EPD rename Oct 2026; history moved here'
                                    || CASE WHEN p.mobile THEN ' for at-site days only (mobile unit)' ELSE '' END,
                        'reviewed', true, 'reviewed_by', 'operator', 'reviewed_at', now()::date::text))))
  FROM lahore_pairs p
 WHERE trim(s.station_id)=p.new_id
   AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(s.metadata_json->'identity'->'aliases','[]'::jsonb)) a
                    WHERE a->>'station_id' = p.old_id);

-- Check: per pair, old_rows + new_rows must equal the STEP 1 sum.
SELECT p.old_name, p.new_name,
       (SELECT count(*) FROM readings r WHERE r.scope_type='station' AND r.scope_key=p.old_id) AS old_rows,
       (SELECT count(*) FROM readings r WHERE r.scope_type='station' AND r.scope_key=p.new_id) AS new_rows
FROM lahore_pairs p ORDER BY p.old_name;

-- COMMIT;   -- or ROLLBACK;
