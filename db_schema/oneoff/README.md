# One-off SQL

Reviewed, hand-run statements that change *data* (never schema). None of these
are executed by the application. Each file has a read-only preview step first;
run it, check the counts, and only then run the write step.

| File | Purpose | Must run before |
|------|---------|-----------------|
| `2026-10_export_membership.sql` | mark the PAQI network stations as exportable (`metadata_json.export.openaq = true`) | deploying the export-membership change (routers/openaq_network.py, routers/public.py), or both exports return empty |
| `2026-10_backfill_units_airvisual.sql` | optional: set `units_pm25/pm10 = 'µg/m³'` on historical airvisual rows that have a value but NULL units | nothing; optional and reversible |
