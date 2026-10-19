# Station Metadata Specification

This document defines the standardized keys for the `stations.metadata_json` JSONB field.

## Schema Convention

The `metadata_json` field stores contextual information about each monitoring station using standardized keys to ensure consistency across analytics and API endpoints.

### Core Fields

| Key | Type | Values | Description |
|-----|------|--------|-------------|
| `site_type` | string | `"traffic"`, `"roadside"`, `"residential"`, `"industrial"`, `"background"`, `"urban"`, `"rural"` | Station environment category |
| `indoor_outdoor` | string | `"indoor"`, `"outdoor"` | Installation location type |
| `height_m` | float | Number | Height above ground level in meters |
| `distance_to_road_m` | float | Number | Approximate distance to nearest major road in meters |

### Site Type Categories

- **`traffic`**: Stations directly exposed to vehicle emissions (roadside, highway)
- **`roadside`**: Near roads but not in direct traffic flow
- **`residential`**: Located in residential areas
- **`industrial`**: Near industrial facilities or zones
- **`background`**: Representative of general urban/rural background levels
- **`urban`**: General urban environment
- **`rural`**: Rural or remote locations

## Usage Examples

### Setting metadata for a traffic station:
```sql
UPDATE stations
SET metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
  'site_type', 'traffic',
  'indoor_outdoor', 'outdoor',
  'height_m', 4.0,
  'distance_to_road_m', 12.0
)
WHERE station_id = 'PKLAH0001';
```

### Querying stations by metadata:
```sql
-- Find all traffic stations
SELECT station_id, name, metadata_json->>'site_type' as site_type
FROM stations 
WHERE metadata_json->>'site_type' = 'traffic';

-- Find outdoor stations above 3m height
SELECT station_id, name, (metadata_json->>'height_m')::float as height_m
FROM stations 
WHERE metadata_json->>'indoor_outdoor' = 'outdoor'
  AND (metadata_json->>'height_m')::float > 3.0;
```

## Analytics Integration

These metadata fields enable:
- **Exposure categorization**: Group stations by exposure type for comparative analysis
- **Data quality assessment**: Account for site characteristics in QC procedures  
- **Regulatory compliance**: Support WHO/EPA monitoring site classification requirements
- **Spatial analysis**: Factor in micro-environmental conditions

## Data Migration

Station metadata is populated through data migrations in the `schema/` directory. See `010_backfill_station_metadata.sql` for the initial metadata assignment.
## Identity, hardware and export membership (ingestion hardening, Oct 2026)

`station_id` is `sha1(country|state|city|name|lat|lon)[:16]` for IQAir stations and therefore
changes when a station is renamed or its coordinates are corrected. Discovery looks a station up
by its provider-native id first and **keeps the legacy `station_id`**; the change is recorded, never
split into a second row. These keys are written by `app/ingestion/identity.py`:

| Key | Written by | Content |
|-----|-----------|---------|
| `identity.native_ids[]` | discovery | `{provider, native_id, since, confidence, evidence}` — one per platform that reports this device |
| `identity.history[]` | discovery | `{at, run_id, event: "rename_or_move", from: {name,lat,lon}, to: {...}, computed_station_id}` (last 50) |
| `identity.aliases[]` | **humans / review tooling only** | `{station_id, provider, relation: "same_device" \| "same_site", confidence, evidence, reviewed: true, reviewed_by, reviewed_at}` — links rows that are the same physical device on another platform (e.g. an IQAir and an OpenAQ copy). Two rows joined by a reviewed `same_device` alias count once for coverage and are **not** independent calibration pairs. |
| `identity.alias_candidates[]` | OpenAQ discovery | machine-proposed matches with evidence (`distance_m`, `name_similarity`, provider hints), `reviewed: false`; never used for anything until promoted to `aliases` by a person |
| `hardware` | humans / attested sources | `{manufacturer, model, confidence: "attested" \| "inferred" \| "unknown", evidence}`. Exports print `unknown` unless confidence is attested/inferred with a model. |
| `export` | one-off SQL (`db_schema/oneoff/`) | `{openaq: bool, network: "PAQI", since, set_by}` — explicit export membership; replaces filtering on `providers.display_name`. |
| `ingest_mode` | OpenAQ discovery | `"shadow"` while a station is ingested but not shown or exported |
| `origin` | OpenAQ discovery | `"external"` or `"hawanama_loop"` (our own data seen via OpenAQ; never ingested) |

Discovery only ever rewrites the keys it owns (`iqair_*`, `location_type`, `data_source`,
`last_updated_utc`, `discovery_method`) plus `identity.native_ids`/`identity.history`; everything
else in `metadata_json` survives every discovery run.
