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