-- 2026-10_backfill_units_airvisual.sql  (OPTIONAL, reversible, run by hand only)
--
-- Historical IQAir rows were written with units_pm25/units_pm10 = NULL (the old
-- extractor set every unit to NULL and the upsert overwrote the column default).
-- IQAir documents PM2.5/PM10 concentrations in µg/m³. This fills the unit only
-- where a value is present and the unit is NULL, one day at a time.
-- Gas units are NOT touched (not attested). Use scripts/backfill_units_airvisual.py
-- for a dry run and per-day execution with counts.
--
-- Preview (read-only):
SELECT date_trunc('day', ts_utc) AS day, count(*) AS rows_missing_units
FROM readings
WHERE source = 'airvisual' AND pm25 IS NOT NULL AND units_pm25 IS NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 30;

-- One day (parameterised by the script; shown here for review):
-- UPDATE readings SET units_pm25 = 'µg/m³'
--  WHERE source = 'airvisual' AND pm25 IS NOT NULL AND units_pm25 IS NULL
--    AND ts_utc >= :day AND ts_utc < :day + interval '1 day';
-- UPDATE readings SET units_pm10 = 'µg/m³'
--  WHERE source = 'airvisual' AND pm10 IS NOT NULL AND units_pm10 IS NULL
--    AND ts_utc >= :day AND ts_utc < :day + interval '1 day';
