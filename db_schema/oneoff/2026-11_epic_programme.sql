-- 2026-11_epic_programme.sql
--
-- Marks the EPIC / PAQI monitors explicitly, so membership no longer depends on the
-- provider label: 8 of them sit under plain "Airvisual" rather than "Airvisual/PAQI".
-- Source: EPIC_monitor_status.xlsx (private repo, tracker as of 2026-07-03; 72 monitors, 71
-- named). 69 named monitors match a station by IQAir name (apostrophes ignored); "Muzaffarabad A"
-- has two station rows (a known duplicate), so 70 rows. Not in the database: "Rawalpindi" (no IQAir
-- name on the tracker) and "Textile Institute of Pakistan Port Qasim KHI" (not listed by IQAir).
--
-- Reversible, additive: only stations.metadata_json->'programme' is written. Export membership
-- (metadata_json.export), the provider and the audit layer are untouched.

CREATE TEMP TABLE epic_monitors (station_id text PRIMARY KEY, epic_name text NOT NULL, duplicate_row boolean NOT NULL);
INSERT INTO epic_monitors VALUES
  ('e91b585ad970c5a3', 'Abbottabad A Mangal', false),
  ('01158ee1c18b5916', 'Abbottabad Thanda Chowa A', false),
  ('c8cc69fb28624319', 'Allama Iqbal Town B LHE', false),
  ('38b3d397130802ec', 'Arifwala B', false),
  ('9122e124034cfa2c', 'Bahawalpur B', false),
  ('1cdb62af79510146', 'Bahawalpur Sadiq Colony B', false),
  ('cd1dd2a904e00adc', 'Bahria Town B LHE', false),
  ('e4c826d6aa908abc', 'Bedian Rd A LHE', false),
  ('0e787a4bf6cdaf47', 'Bedian Thethar Rd LHE', false),
  ('796c85385b861235', 'Burewala Nehar Bunglow Rd B', false),
  ('11996bf11c468bcd', 'Burki Rd Paragon B LHE', false),
  ('be7784d8f3fdae0c', 'Clifton Block 1 C KHI', false),
  ('13fe5e46f3cb227a', 'DHA Phase 6 B LHE', false),
  ('4f59ca7d3d565a1f', 'Dera Ghazi Khan Civil Lines B', false),
  ('8bb4d221cb246bad', 'Dera Ghazi Khan Jampur Rd B', false),
  ('7f5f6ca4991dc987', 'Faisal Cantonment A KHI', false),
  ('8acaed7056bf75a5', 'Faisalabad Civil Lines B', false),
  ('3d0d74874af168c6', 'Faisalabad Gatwala Canal Rd A', false),
  ('2c610495a93a39b7', 'Faisalabad People''s Colony B', false),
  ('fd63fc79c2c70a81', 'Faisalabad Raza Garden B', false),
  ('6a9103245e5ea261', 'Ferozepur Rd A LHE', false),
  ('b96709735b7cf922', 'Gujranwala Cantt B', false),
  ('305e0ea290786cc3', 'Gujranwala SFL', false),
  ('2edb5b118a3798a8', 'Gujrat GT Road B', false),
  ('d85f50027eac7352', 'Gujrat Model Town B', false),
  ('5bb959d241332344', 'Gurumangat Rd B LHE', false),
  ('802256e961daca0c', 'HANDS Gadap Town KHI', false),
  ('c2072b3839f4a4d6', 'Icchra Maqbool Rd LHE', false),
  ('794c407d1677dc5f', 'Islamabad H11 A', false),
  ('c569281a9aa0c0fe', 'Jamshed Road C KHI', false),
  ('66ae81afcb7e7343', 'Jauharabad B', false),
  ('0cdcfa8e30033019', 'Jhelum B', false),
  ('e99939621477c9f9', 'Johar Road C KHI', false),
  ('218294709939d0a9', 'Johar Town A LHE', false),
  ('f906b5a06747fc83', 'Johar Town B LHE', false),
  ('76467191ad5322a8', 'Kasur B', false),
  ('d9692489500b5a85', 'Khanewal B', false),
  ('c7740bdc4c341a0f', 'Kharian Cantt B (GT Rd)', false),
  ('8338ab638cbf64d7', 'Kot Adu KAPCO B', false),
  ('111cf77cc226d5b2', 'Kot Adu PARCO B', false),
  ('0bd9ce5023d669ab', 'Mansehra Dhodial A', false),
  ('7c58332b82ed0928', 'Mirza Hospital Jhelum', false),
  ('54042139917a1eda', 'Model Town A LHE', false),
  ('01cb11a02fbad27d', 'Model Town B LHE', false),
  ('497da9bfc67512e5', 'Model Town Link Rd B LHE', false),
  ('c3b42d69b2c559f1', 'Multan Industrial Estate A', false),
  ('3cc3fa1132247f70', 'Multan Northern Bypass B', false),
  ('b4e49ca5f648129f', 'Muslim Town LHE B', false),
  ('b33f66a884103034', 'Muzaffarabad A', true),
  ('e327aba287a274e7', 'Muzaffarabad A', true),
  ('aa8f11d2d8d00316', 'Muzaffarabad Eid Gah Rd Makri A', false),
  ('b397411f82aa726f', 'Okara Canal View B', false),
  ('b4d3ddba95f1d321', 'Old Clifton Seven Towers', false),
  ('a166fd469337ee9d', 'PTC Jhelum GT Rd', false),
  ('961403b36a531da2', 'Peshawar A Hayatabad', false),
  ('7db60a1dea163aab', 'Rahim Yar Khan Canal Rd B', false),
  ('dfad83f506123b3b', 'Rawalakot A', false),
  ('c7def5483f121d71', 'Rawalpindi A GT Road', false),
  ('7b0afe37f5a355a8', 'Sahiwal Arra Tulla Rd B', false),
  ('46113127236d948d', 'Sargodha Defence View Society A', false),
  ('79b6b19e01cb0437', 'Sargodha Queens Rd B', false),
  ('40117edac7f60f7f', 'Sargodha Umer Park B', false),
  ('60b141be1a707d5c', 'Shadman Market B LHE', false),
  ('88071a0043afc8d7', 'Sialkot A', false),
  ('254cd424764cefd4', 'Sialkot Aziz Garden B', false),
  ('abbe7548237f4f49', 'Sialkot Cantt B', false),
  ('69eb7d74d10a5c7e', 'TIP City Office - LIH', false),
  ('fe87f56221977106', 'Tajpura', false),
  ('642b8a430f83f341', 'Tariq Road C KHI', false),
  ('28a65f8911ebba32', 'Vehari B', false);

-- STEP 1 (read-only): expect 70 rows, all found, none already carrying a programme key.
SELECT e.epic_name, s.station_id, s.name, p.display_name AS network, s.active,
       s.metadata_json->'export'->>'openaq' AS exported, s.metadata_json->'programme' AS existing
FROM epic_monitors e
LEFT JOIN stations s ON s.station_id = e.station_id
LEFT JOIN providers p ON p.id = s.provider_id
ORDER BY e.epic_name;

-- STEP 2a (transaction; COMMIT only after STEP 1 looks right).
BEGIN;

UPDATE stations s
   SET metadata_json = COALESCE(s.metadata_json, '{}'::jsonb)
       || jsonb_build_object('programme', jsonb_strip_nulls(jsonb_build_object(
              'name', 'EPIC',
              'partner', 'PAQI',
              'listed_as', e.epic_name,
              'duplicate_row', CASE WHEN e.duplicate_row THEN true END,
              'source', 'EPIC_monitor_status.xlsx (tracker as of 2026-07-03)',
              'set_by', 'oneoff_2026-11_epic_programme',
              'since', now()::date::text)))
  FROM epic_monitors e
 WHERE s.station_id = e.station_id
   AND NOT (COALESCE(s.metadata_json, '{}'::jsonb) ? 'programme');   -- idempotent: a re-run writes nothing

SELECT count(*) AS epic_rows FROM stations WHERE metadata_json->'programme'->>'name' = 'EPIC';   -- expect 70

-- COMMIT;   -- or ROLLBACK;

-- STEP 2b (PROPOSAL, needs a decision): add the EPIC monitors that are not yet in the PAQI
-- export (OpenAQ + partner API). This publishes their data. The duplicate "Muzaffarabad A" row is
-- excluded because its twin is already exported.
-- UPDATE stations s
--    SET metadata_json = s.metadata_json
--        || jsonb_build_object('export', jsonb_build_object(
--               'openaq', true, 'network', 'PAQI', 'since', now()::date::text,
--               'set_by', 'oneoff_2026-11_epic_programme'))
--  WHERE s.metadata_json->'programme'->>'name' = 'EPIC'
--    AND NOT COALESCE((s.metadata_json->'programme'->>'duplicate_row')::boolean, false)
--    AND COALESCE((s.metadata_json->'export'->>'openaq')::boolean, false) IS NOT TRUE;

-- To undo for one station:
-- UPDATE stations SET metadata_json = metadata_json - 'programme' WHERE station_id = '<id>';
