#!/bin/bash
# Comprehensive test suite for Hawanama Export API
# Tests various filter combinations and data types

set -e

# Configuration
API_URL="https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv"
OUTPUT_DIR="./export_tests"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Check for API token
if [ -z "$HAWANAMA_API_TOKEN" ]; then
    echo -e "${RED}Error: HAWANAMA_API_TOKEN environment variable not set${NC}"
    echo "Usage: export HAWANAMA_API_TOKEN='your_token_here'"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Test counter
PASSED=0
FAILED=0
TOTAL=0

# Function to run a test
run_test() {
    local test_name="$1"
    local query_params="$2"
    local expected_min_rows="${3:-1}"

    ((TOTAL++))

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}Test $TOTAL: $test_name${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo "Query: $query_params"

    local output_file="$OUTPUT_DIR/test${TOTAL}_${TIMESTAMP}.csv"
    local url="${API_URL}?${query_params}"

    # Make request
    local http_code=$(curl -w "%{http_code}" -o "$output_file" \
        -H "Authorization: Bearer $HAWANAMA_API_TOKEN" \
        --silent \
        --max-time 120 \
        "$url")

    # Check status
    if [ "$http_code" -ne 200 ]; then
        echo -e "${RED}✗ FAILED: HTTP $http_code${NC}"
        cat "$output_file"
        ((FAILED++))
        return
    fi

    # Count rows
    local row_count=$(($(wc -l < "$output_file") - 1))
    local file_size=$(du -h "$output_file" | cut -f1)

    # Validate
    if [ $row_count -ge $expected_min_rows ]; then
        echo -e "${GREEN}✓ PASSED: $row_count rows, $file_size${NC}"
        ((PASSED++))

        # Show sample
        echo "Sample (first 2 data rows):"
        head -n 3 "$output_file" | tail -n 2
    else
        echo -e "${RED}✗ FAILED: Expected at least $expected_min_rows rows, got $row_count${NC}"
        ((FAILED++))
    fi
}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Hawanama Export API - Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Timestamp: $TIMESTAMP"
echo "API URL: $API_URL"
echo ""

# Test 1: Basic query (last 1 day, default PM2.5)
run_test "Basic Query - Last 1 Day" \
    "days_back=1" \
    0

# Test 2: All pollutants, last 7 days
run_test "All Pollutants - Last 7 Days" \
    "parameters=all&days_back=7" \
    0

# Test 3: Hourly aggregation, last 30 days
run_test "Hourly Aggregation - Last 30 Days" \
    "data_type=hourly&days_back=30" \
    0

# Test 4: Daily aggregation, last 365 days
run_test "Daily Aggregation - Last Year" \
    "data_type=daily&days_back=365" \
    0

# Test 5: Punjab province filter
run_test "Province Filter - Punjab" \
    "province=Punjab&days_back=7" \
    0

# Test 6: Lahore city filter
run_test "City Filter - Lahore" \
    "city=Lahore&days_back=7" \
    0

# Test 7: Specific date range
run_test "Date Range - 2024 Full Year" \
    "start_date=2024-01-01&end_date=2024-12-31&data_type=daily" \
    0

# Test 8: Multiple pollutants subset
run_test "Pollutant Subset - PM2.5 + PM10" \
    "parameters=pm25,pm10&days_back=30" \
    0

# Test 9: Combined filters - Punjab + Daily + All pollutants
run_test "Combined - Punjab + Daily + All Pollutants" \
    "province=Punjab&data_type=daily&parameters=all&days_back=90" \
    0

# Test 10: Lahore + Hourly + Last week
run_test "Combined - Lahore + Hourly + Week" \
    "city=Lahore&data_type=hourly&days_back=7" \
    0

# Test 11: Historical range (2020-2021, daily)
run_test "Historical - 2020-2021 Daily" \
    "start_date=2020-01-01&end_date=2021-12-31&data_type=daily&parameters=all" \
    0

# Test 12: Max rows limit test
run_test "Safety - Max Rows Limit" \
    "days_back=1&max_rows=100" \
    0

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Suite Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Total Tests: $TOTAL"
echo -e "${GREEN}Passed: $PASSED${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $FAILED${NC}"
else
    echo -e "${GREEN}Failed: $FAILED${NC}"
fi
echo ""

# Calculate success rate
SUCCESS_RATE=$(echo "scale=2; $PASSED * 100 / $TOTAL" | bc)
echo "Success Rate: ${SUCCESS_RATE}%"
echo ""
echo "Test artifacts saved in: $OUTPUT_DIR"

# Exit with error if any tests failed
if [ $FAILED -gt 0 ]; then
    exit 1
fi

echo -e "${GREEN}All tests passed! ✓${NC}"
