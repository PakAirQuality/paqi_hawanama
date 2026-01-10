# Hawanama Export API - Test Scripts

This directory contains test scripts for validating the comprehensive export endpoint functionality.

## Setup

### 1. Set API Token

All tests require an API token:

```bash
export HAWANAMA_API_TOKEN='your_api_token_here'
```

### 2. Install Dependencies (Python tests only)

```bash
pip install requests
```

## Test Scripts

### 1. Full Historical Export Test

**Purpose:** Test exporting ALL stations, ALL pollutants from 2018 to 2025

**Bash version:**
```bash
./test_export_all_historical.sh
```

**Python version:**
```bash
./test_export_python.py --full-historical
# or simply
./test_export_python.py
```

**What it tests:**
- Complete historical data export (2018-2025)
- All pollutants (pm25, pm10, no2, so2, co, o3)
- Raw data (individual readings)
- Maximum row limit (5M rows)
- Streaming performance
- Data validation

**Expected output:**
- CSV file with all historical data
- Performance metrics (throughput, bandwidth)
- Data summary (row count, date range, stations)

### 2. Comprehensive Test Suite

**Purpose:** Run multiple tests covering various filter combinations

**Bash version:**
```bash
./test_export_suite.sh
```

**Python version:**
```bash
./test_export_python.py --suite
```

**What it tests:**
1. Basic query (last 1 day)
2. All pollutants (last 7 days)
3. Hourly aggregation (last 30 days)
4. Daily aggregation (last year)
5. Province filter (Punjab)
6. City filter (Lahore)
7. Date range (2024 full year)
8. Pollutant subset (PM2.5 + PM10)
9. Combined filters (Punjab + Daily + All pollutants)
10. Lahore + Hourly + Week
11. Historical range (2020-2021 daily)
12. Max rows limit test

**Expected output:**
- Pass/fail status for each test
- Success rate percentage
- CSV files for each test
- Performance summary

## Output Location

All test outputs are saved in:
```
./export_tests/
```

Each file is timestamped to prevent overwrites.

## Interpreting Results

### Success Indicators

✓ **HTTP 200**: Request succeeded
✓ **Row count > 0**: Data was returned (unless testing empty filters)
✓ **Valid CSV**: File can be parsed
✓ **Performance metrics**: Within expected ranges

### Common Issues

**401 Unauthorized:**
- Check that HAWANAMA_API_TOKEN is set correctly
- Verify token is valid

**Timeout:**
- Large historical exports may take 10-15 minutes
- Use `data_type=daily` for faster large-range exports
- Check network connectivity

**Empty results (0 rows):**
- Verify date range has data
- Check filter values (province/city names)
- Confirm stations exist for given filters

## Performance Benchmarks

Based on production testing:

| Dataset | Rows | Size | Time | Throughput |
|---------|------|------|------|------------|
| 1 day, all stations | ~10K | 2 MB | 2s | 5K rows/sec |
| 30 days, daily | ~1K | 200 KB | 1s | 1K rows/sec |
| 365 days, daily | ~12K | 2.5 MB | 10s | 1.2K rows/sec |
| 2018-2025, daily | ~100K | 20 MB | 1min | 1.7K rows/sec |
| 2018-2025, raw (all) | ~2M+ | 400+ MB | 15min | 2K rows/sec |

## Troubleshooting

### Test fails with "command not found"

Make scripts executable:
```bash
chmod +x test_export_*.sh test_export_*.py
```

### Python script fails with import error

Install requests:
```bash
pip install requests
```

### Curl progress bar not working

Update curl or use Python version:
```bash
./test_export_python.py
```

### Tests timeout

Increase timeout in scripts or use daily aggregation:
- Bash: Edit `--max-time` value in curl command
- Python: Edit `timeout` parameter in requests.get()

## Example Usage

### Quick validation test
```bash
# Test basic functionality (fast, ~2 seconds)
export HAWANAMA_API_TOKEN='your_token'
./test_export_suite.sh
```

### Full historical export
```bash
# Export all data from 2018-2025 (slow, ~15 minutes)
export HAWANAMA_API_TOKEN='your_token'
./test_export_all_historical.sh

# Output will be in:
# ./export_tests/all_stations_2018_2025_TIMESTAMP.csv
```

### Custom test with Python
```python
from test_export_python import run_test

# Custom test
run_test(
    "My Custom Test",
    {
        'province': 'Sindh',
        'data_type': 'hourly',
        'parameters': 'pm25,pm10',
        'days_back': '90'
    },
    expected_min_rows=100
)
```

## API Monitoring

The API logs all export requests with details:
- Query parameters (province, city, station_ids, etc.)
- Data type and pollutants selected
- Time range requested
- Number of stations matched
- Row count exported
- Duration

Check Cloud Run logs for detailed request information:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=hawanama" \
  --project=hawanama-2 \
  --limit=50 \
  --format=json
```

## Contributing

To add new tests:

1. Add test case to `test_export_suite.sh` or `test_export_python.py`
2. Update this README with test description
3. Verify test passes before committing

## Support

For issues or questions:
- GitHub Issues: https://github.com/PakAirQuality/hawanama/issues
- Documentation: See export_api.md
