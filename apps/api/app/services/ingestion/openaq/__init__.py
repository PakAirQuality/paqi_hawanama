"""
OpenAQ v3 adapter (shadow mode).

An independent ingestion path with its own credential, budget and checkpoints.
Locations become `stations` rows under provider code 'openaq' with active=false
and metadata_json.ingest_mode='shadow'; measurements become `readings` rows with
source='openaq'. Nothing here is shown on the public map or exported until a
documented cutover flips those flags per station.

Modules: models (typed API contracts), client (quota-reserved HTTP + pagination
guard), windows (checkpoint arithmetic), normalize (measurement → reading row),
identity (loop exclusion + alias candidates), repository (Postgres / in-memory),
discovery and ingest (the two tasks).
"""
