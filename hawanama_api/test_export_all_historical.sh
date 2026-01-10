#!/bin/bash
# Test script: Export ALL stations, ALL data from 2018 to 2025
# This is the comprehensive historical export test

set -e  # Exit on error

# Configuration
API_URL="https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv"
OUTPUT_DIR="./export_tests"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check for API token
if [ -z "$HAWANAMA_API_TOKEN" ]; then
    echo -e "${RED}Error: HAWANAMA_API_TOKEN environment variable not set${NC}"
    echo "Usage: export HAWANAMA_API_TOKEN='your_token_here'"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Hawanama Export Test: Full Historical${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Test Configuration:${NC}"
echo "  Date Range: 2018-01-01 to 2025-12-31"
echo "  Pollutants: ALL (pm25, pm10, no2, so2, co, o3)"
echo "  Data Type: raw (individual readings)"
echo "  Stations: ALL (entire database)"
echo "  Max Rows: 5,000,000 (hard cap)"
echo "  Output: $OUTPUT_DIR/all_stations_2018_2025_${TIMESTAMP}.csv"
echo ""

# Build request URL
REQUEST_URL="${API_URL}?start_date=2018-01-01&end_date=2025-12-31&parameters=all&data_type=raw&max_rows=5000000"

echo -e "${YELLOW}Starting export...${NC}"
echo "Request URL: $REQUEST_URL"
echo ""

# Start timer
START_TIME=$(date +%s)

# Make request with progress bar
OUTPUT_FILE="$OUTPUT_DIR/all_stations_2018_2025_${TIMESTAMP}.csv"
HTTP_CODE=$(curl -w "%{http_code}" -o "$OUTPUT_FILE" \
    -H "Authorization: Bearer $HAWANAMA_API_TOKEN" \
    --progress-bar \
    --max-time 900 \
    "$REQUEST_URL")

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Export Results${NC}"
echo -e "${BLUE}========================================${NC}"

# Check HTTP status
if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ HTTP Status: $HTTP_CODE (Success)${NC}"
else
    echo -e "${RED}✗ HTTP Status: $HTTP_CODE (Error)${NC}"
    echo "Response content:"
    cat "$OUTPUT_FILE"
    exit 1
fi

# Get file size
FILE_SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
FILE_SIZE_BYTES=$(wc -c < "$OUTPUT_FILE")
FILE_SIZE_MB=$(echo "scale=2; $FILE_SIZE_BYTES / 1048576" | bc)

echo -e "${GREEN}✓ File Size: $FILE_SIZE ($FILE_SIZE_MB MB)${NC}"
echo -e "${GREEN}✓ Duration: ${MINUTES}m ${SECONDS}s${NC}"

# Count rows (excluding header)
ROW_COUNT=$(($(wc -l < "$OUTPUT_FILE") - 1))
echo -e "${GREEN}✓ Row Count: $(printf "%'d" $ROW_COUNT) rows${NC}"

# Show first few lines of CSV (header + 3 rows)
echo ""
echo -e "${YELLOW}CSV Preview (first 4 lines):${NC}"
head -n 4 "$OUTPUT_FILE"

# Extract and show column count
COLUMN_COUNT=$(head -n 1 "$OUTPUT_FILE" | tr ',' '\n' | wc -l)
echo ""
echo -e "${YELLOW}CSV Structure:${NC}"
echo "  Columns: $COLUMN_COUNT"

# Show date range in data
echo ""
echo -e "${YELLOW}Date Range in Data:${NC}"
FIRST_DATE=$(tail -n +2 "$OUTPUT_FILE" | head -n 1 | cut -d',' -f8 | cut -d'T' -f1)
LAST_DATE=$(tail -n 1 "$OUTPUT_FILE" | cut -d',' -f8 | cut -d'T' -f1)
echo "  First timestamp: $FIRST_DATE"
echo "  Last timestamp: $LAST_DATE"

# Count unique stations
echo ""
echo -e "${YELLOW}Analyzing stations...${NC}"
UNIQUE_STATIONS=$(tail -n +2 "$OUTPUT_FILE" | cut -d',' -f2 | sort -u | wc -l)
echo "  Unique stations: $UNIQUE_STATIONS"

# Calculate average throughput
THROUGHPUT=$(echo "scale=2; $ROW_COUNT / $DURATION" | bc)
echo ""
echo -e "${YELLOW}Performance Metrics:${NC}"
echo "  Throughput: $THROUGHPUT rows/second"
echo "  Bandwidth: $(echo "scale=2; $FILE_SIZE_MB / $DURATION" | bc) MB/second"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Test PASSED ✓${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Output saved to: $OUTPUT_FILE"
