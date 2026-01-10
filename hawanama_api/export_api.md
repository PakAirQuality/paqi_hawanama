# Hawanama API v1 — Station Readings Export (Multifunctional)

This document describes the **comprehensive export endpoint** for pulling station-level air-quality readings across one station, a filtered subset, or **all stations** — in streaming CSV format.

---

## Base URL

- Production: `https://hawanama-152782825429.asia-south1.run.app`
- Public: `https://hawanama.org` (when DNS configured)

All endpoints are under: `/api/v1`

---

## Authentication

All export endpoints require an API token.

Send the token via the `Authorization` header:
```bash
Authorization: Bearer YOUR_API_TOKEN
```

If the token is missing/invalid, the API returns `401 Unauthorized`.

---

## Timezone & Date Semantics

- All timestamps in the database are stored in **UTC**
- API returns timestamps in **ISO 8601 format** (e.g., `2024-01-15T08:30:00`)
- Date inputs use `YYYY-MM-DD` format
- `start_date` is **inclusive** (00:00:00 UTC)
- `end_date` is **exclusive** (treated as start of next day, 00:00:00 UTC)
- For Pakistan local time (UTC+5), add 5 hours to UTC timestamps

---

# Main Export Endpoint

## GET `/api/v1/exports/station-readings-csv`

**Multifunctional streaming CSV export** with comprehensive filtering, pollutant selection, and temporal aggregation.

### Key Features

✅ **Query ALL stations** in database (no filters needed)
✅ **Geographic filters**: province, city, station_id(s)
✅ **Provider filter**: by data source/provider code
✅ **Flexible pollutant selection**: pm25, pm10, no2, so2, co, o3
✅ **Aggregation modes**: raw, hourly, daily
✅ **Streaming response**: memory-efficient for large datasets
✅ **100% backward compatible**: existing API calls work unchanged

---

## Query Parameters

### Time Range (choose one method)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `days_back` | integer | No | Number of days back from now (default: 1, max: 3650) |
| `start_date` | string | No | Start date in YYYY-MM-DD format (overrides days_back) |
| `end_date` | string | No | End date in YYYY-MM-DD format (requires start_date) |

**Examples:**
- `?days_back=30` - Last 30 days
- `?start_date=2018-01-01&end_date=2025-12-31` - Full date range
- No parameters - Last 1 day (default)

---

### Geographic Filters (all optional)

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `province` | string | Filter by province/state name | `Punjab`, `Sindh` |
| `city` | string | Filter by city name | `Lahore`, `Karachi` |
| `station_id` | string[] | Filter by specific station(s) | `ABC123` or `ABC123,DEF456` |

**Station ID formats:**
- Single: `?station_id=ABC123`
- Multiple (comma-separated): `?station_id=ABC123,DEF456,GHI789`
- Multiple (repeated param): `?station_id=ABC123&station_id=DEF456`

**Notes:**
- Province/city matching is case-insensitive
- Omit all filters to query **all stations** in database

---

### Data Selection

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parameters` | string | `pm25` | Pollutants to include (see below) |
| `data_type` | enum | `raw` | Resolution: `raw` \| `hourly` \| `daily` |
| `provider` | string[] | all | Filter by provider code(s) |

#### Parameter Options

**Pollutant Selection (`parameters`):**
- `all` - All available pollutants (pm25, pm10, no2, so2, co, o3)
- `pm25` - PM2.5 only (default, legacy behavior)
- `pm25,pm10,no2` - Specific subset (comma-separated)

**Accepted aliases:**
- `pm2.5`, `pm2_5`, `pm_2_5` → `pm25`
- `carbon_monoxide`, `carbon-monoxide`, `monoxide` → `co`

**Data Type (`data_type`):**
- `raw` - Individual readings as recorded (default)
- `hourly` - 1-hour time buckets with averages + sample counts
- `daily` - Daily aggregates with averages + sample counts

**Provider Filter (`provider`):**
- Filter by data provider code (e.g., `iqair`, `airvisual`)
- Comma-separated or repeated parameter format

---

### Safety & Performance

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_rows` | integer | 500,000 | Safety cap on rows (hard limit: 5,000,000) |

**Notes:**
- For large exports (>1M rows), consider using `data_type=daily` for aggregation
- API uses streaming response to handle large datasets efficiently
- Client disconnect detection prevents wasted server resources

---

## Response Format

### CSV Structure

**Base Columns (always included):**
```csv
id,station_name,latitude,longitude,city_name,state_name,country_name,timestamp_utc,
aqi_us,aqi_cn,main_pollutant_us,main_pollutant_cn,
temperature_celsius,humidity_percent,pressure_hpa,
wind_speed_ms,wind_direction_degrees,heat_index_celsius,
weather_icon,qc_state,provider_code,provider_name
```

**Aggregated Data Columns (when `data_type=hourly|daily`):**
```csv
...,sample_count,qc_ok_count
```

**Dynamic Pollutant Columns (based on `parameters`):**
```csv
...,pm25_ugm3,pm25_units,pm10_ugm3,pm10_units,no2,no2_units,so2,so2_units,co,co_units,o3,o3_units
```

### Response Headers

```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename=hawanama_station_readings_{data_type}_{daterange}_{timestamp}.csv
```

---

## Usage Examples

### 1. Query ALL Stations (Entire Database)

```bash
# All stations, PM2.5 only, last 30 days
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?days_back=30"

# All stations, all pollutants, full historical range (2018-2025)
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?parameters=all&start_date=2018-01-01&end_date=2025-12-31" \
  -o all_stations_2018_2025.csv
```

### 2. Province/City Filtering

```bash
# Punjab province, daily aggregates, last year
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?province=Punjab&data_type=daily&days_back=365"

# Lahore city, hourly data, PM2.5 and PM10
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?city=Lahore&parameters=pm25,pm10&data_type=hourly&days_back=7"
```

### 3. Specific Stations

```bash
# Single station, all parameters, last 90 days
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?station_id=ABC123&parameters=all&days_back=90"

# Multiple stations, PM2.5 only, specific date range
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?station_id=ABC123,DEF456&start_date=2024-01-01&end_date=2024-12-31"
```

### 4. Provider-Specific Data

```bash
# IQAir provider only, all pollutants
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?provider=iqair&parameters=all&days_back=30"
```

### 5. Large Historical Exports

```bash
# Multi-year export with daily aggregation (recommended for large ranges)
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?parameters=all&data_type=daily&start_date=2020-01-01&end_date=2024-12-31&max_rows=2000000" \
  -o hawanama_4year_daily.csv

# Progress monitoring with verbose output
curl -H "Authorization: Bearer TOKEN" --progress-bar \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?days_back=365" \
  -o output.csv
```

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "start_date must be before end_date"
}
```

### 401 Unauthorized
```json
{
  "detail": "Invalid or missing API token"
}
```

### 422 Unprocessable Entity
```json
{
  "detail": "Invalid parameters entry 'xyz'. Allowed: all,co,no2,o3,pm10,pm25,so2 (aliases: pm2.5, carbon_monoxide)."
}
```

### 500 Internal Server Error
```json
{
  "detail": "Failed to export station readings"
}
```

---

## Performance Considerations

### Recommended Practices

1. **Large date ranges**: Use `data_type=daily` for multi-year exports
2. **Specific needs**: Filter by province/city to reduce dataset size
3. **Testing**: Start with `days_back=1` to verify query structure
4. **Monitoring**: Use `--progress-bar` or `-#` with curl for large downloads

### Expected Response Times

| Dataset Size | Raw Data | Hourly | Daily |
|--------------|----------|--------|-------|
| 1 day, 1 city | ~2 sec | ~1 sec | <1 sec |
| 30 days, 1 province | ~15 sec | ~5 sec | ~2 sec |
| 365 days, all stations | ~3 min | ~45 sec | ~10 sec |
| 2018-2025, all stations | ~15 min | ~5 min | ~1 min |

**Notes:**
- Times vary based on data density and network speed
- Streaming ensures memory-efficient processing
- Server-side timeout: 10 minutes for Cloud Run

---

## Legacy Compatibility

The endpoint maintains **100% backward compatibility** with the original API:

**Original behavior (unchanged):**
```bash
curl -H "Authorization: Bearer TOKEN" \
  "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv?days_back=7"
```

Returns:
- PM2.5 data only
- Raw readings (not aggregated)
- All active stations
- Same CSV column structure

**New capabilities are opt-in** via additional query parameters.

---

## API Changelog

### Version 1.1 (2025-01-10)
- ✅ Added province/city/station_id filters
- ✅ Added provider filter
- ✅ Added flexible pollutant selection (`parameters`)
- ✅ Added aggregation modes (`data_type`: hourly, daily)
- ✅ Added start_date/end_date for explicit date ranges
- ✅ Added sample_count and qc_ok_count for aggregated data
- ✅ Improved streaming performance with client disconnect detection
- ✅ Enhanced logging with comprehensive query parameter tracking

### Version 1.0 (Initial)
- Basic station readings export
- PM2.5 only
- days_back parameter
- CSV streaming

---

## Support & Contact

For API issues or feature requests:
- GitHub: https://github.com/PakAirQuality/hawanama
- Documentation: See CLAUDE.md in repository
