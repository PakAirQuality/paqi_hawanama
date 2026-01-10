#!/usr/bin/env python3
"""
Hawanama Export API - Python Test Suite
Tests the comprehensive export endpoint with various configurations
"""

import os
import sys
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Configuration
API_URL = "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/station-readings-csv"
OUTPUT_DIR = Path("./export_tests")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# Colors for terminal output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.total = 0

def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{Colors.BLUE}{'=' * 50}{Colors.NC}")
    print(f"{Colors.BLUE}{text}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")

def run_test(
    test_name: str,
    query_params: Dict[str, str],
    expected_min_rows: int = 0,
    result: TestResult = None
) -> bool:
    """
    Run a single API test

    Args:
        test_name: Description of the test
        query_params: Dictionary of query parameters
        expected_min_rows: Minimum expected rows (default: 0)
        result: TestResult object to track statistics

    Returns:
        bool: True if test passed, False otherwise
    """
    if result:
        result.total += 1

    print(f"\n{Colors.CYAN}{'=' * 50}{Colors.NC}")
    print(f"{Colors.CYAN}Test: {test_name}{Colors.NC}")
    print(f"{Colors.CYAN}{'=' * 50}{Colors.NC}")
    print(f"Query params: {query_params}")

    # Get API token
    api_token = os.environ.get('HAWANAMA_API_TOKEN')
    if not api_token:
        print(f"{Colors.RED}✗ FAILED: HAWANAMA_API_TOKEN not set{Colors.NC}")
        if result:
            result.failed += 1
        return False

    # Prepare output file
    output_file = OUTPUT_DIR / f"test_{result.total if result else 0}_{TIMESTAMP}.csv"

    # Make request
    headers = {'Authorization': f'Bearer {api_token}'}
    start_time = time.time()

    try:
        response = requests.get(
            API_URL,
            params=query_params,
            headers=headers,
            stream=True,
            timeout=180
        )

        # Check status code
        if response.status_code != 200:
            print(f"{Colors.RED}✗ FAILED: HTTP {response.status_code}{Colors.NC}")
            print(f"Response: {response.text[:500]}")
            if result:
                result.failed += 1
            return False

        # Save response to file
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        duration = time.time() - start_time

        # Analyze results
        with open(output_file, 'r') as f:
            lines = f.readlines()
            row_count = len(lines) - 1  # Subtract header
            header = lines[0].strip()
            column_count = len(header.split(','))

        file_size = output_file.stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        # Validate
        if row_count >= expected_min_rows:
            print(f"{Colors.GREEN}✓ PASSED{Colors.NC}")
            print(f"  Rows: {row_count:,}")
            print(f"  Columns: {column_count}")
            print(f"  Size: {file_size_mb:.2f} MB")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Throughput: {row_count/duration:.0f} rows/sec")

            if result:
                result.passed += 1
            return True
        else:
            print(f"{Colors.RED}✗ FAILED: Expected >= {expected_min_rows} rows, got {row_count}{Colors.NC}")
            if result:
                result.failed += 1
            return False

    except requests.exceptions.RequestException as e:
        print(f"{Colors.RED}✗ FAILED: Request error - {e}{Colors.NC}")
        if result:
            result.failed += 1
        return False
    except Exception as e:
        print(f"{Colors.RED}✗ FAILED: {e}{Colors.NC}")
        if result:
            result.failed += 1
        return False

def test_full_historical_export():
    """Test: Export ALL data from 2018 to 2025"""
    print_header("TEST: Full Historical Export (2018-2025)")

    query_params = {
        'start_date': '2018-01-01',
        'end_date': '2025-12-31',
        'parameters': 'all',
        'data_type': 'raw',
        'max_rows': '5000000'
    }

    api_token = os.environ.get('HAWANAMA_API_TOKEN')
    if not api_token:
        print(f"{Colors.RED}Error: HAWANAMA_API_TOKEN environment variable not set{Colors.NC}")
        sys.exit(1)

    print(f"\n{Colors.YELLOW}Configuration:{Colors.NC}")
    print(f"  Date Range: 2018-01-01 to 2025-12-31")
    print(f"  Pollutants: ALL (pm25, pm10, no2, so2, co, o3)")
    print(f"  Data Type: raw (individual readings)")
    print(f"  Stations: ALL (entire database)")
    print(f"  Max Rows: 5,000,000")

    output_file = OUTPUT_DIR / f"all_stations_2018_2025_{TIMESTAMP}.csv"

    print(f"\n{Colors.YELLOW}Starting export...{Colors.NC}")
    headers = {'Authorization': f'Bearer {api_token}'}
    start_time = time.time()

    try:
        response = requests.get(
            API_URL,
            params=query_params,
            headers=headers,
            stream=True,
            timeout=900  # 15 minutes
        )

        if response.status_code != 200:
            print(f"{Colors.RED}✗ HTTP {response.status_code}{Colors.NC}")
            print(response.text)
            return False

        # Stream to file with progress
        downloaded = 0
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded % (1024 * 1024) == 0:  # Every MB
                    print(f"\r{Colors.YELLOW}Downloaded: {downloaded / (1024*1024):.1f} MB{Colors.NC}", end='')

        print()  # New line after progress
        duration = time.time() - start_time

        # Analyze results
        print(f"\n{Colors.BLUE}{'=' * 50}{Colors.NC}")
        print(f"{Colors.BLUE}Export Results{Colors.NC}")
        print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")

        file_size = output_file.stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        print(f"{Colors.GREEN}✓ File Size: {file_size_mb:.2f} MB{Colors.NC}")
        print(f"{Colors.GREEN}✓ Duration: {int(duration // 60)}m {int(duration % 60)}s{Colors.NC}")

        # Count rows
        with open(output_file, 'r') as f:
            row_count = sum(1 for _ in f) - 1  # Subtract header

        print(f"{Colors.GREEN}✓ Row Count: {row_count:,} rows{Colors.NC}")
        print(f"\n{Colors.YELLOW}Performance Metrics:{Colors.NC}")
        print(f"  Throughput: {row_count/duration:.0f} rows/second")
        print(f"  Bandwidth: {file_size_mb/duration:.2f} MB/second")

        print(f"\n{Colors.GREEN}Test PASSED ✓{Colors.NC}")
        print(f"Output saved to: {output_file}")
        return True

    except Exception as e:
        print(f"{Colors.RED}✗ FAILED: {e}{Colors.NC}")
        return False

def run_test_suite():
    """Run comprehensive test suite"""
    print_header("Hawanama Export API - Test Suite")
    print(f"Timestamp: {TIMESTAMP}")
    print(f"API URL: {API_URL}")

    # Check for API token
    if not os.environ.get('HAWANAMA_API_TOKEN'):
        print(f"{Colors.RED}Error: HAWANAMA_API_TOKEN environment variable not set{Colors.NC}")
        print("Usage: export HAWANAMA_API_TOKEN='your_token_here'")
        sys.exit(1)

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    result = TestResult()

    # Test 1: Basic query
    run_test(
        "Basic Query - Last 1 Day",
        {'days_back': '1'},
        expected_min_rows=0,
        result=result
    )

    # Test 2: All pollutants
    run_test(
        "All Pollutants - Last 7 Days",
        {'parameters': 'all', 'days_back': '7'},
        expected_min_rows=0,
        result=result
    )

    # Test 3: Hourly aggregation
    run_test(
        "Hourly Aggregation - Last 30 Days",
        {'data_type': 'hourly', 'days_back': '30'},
        expected_min_rows=0,
        result=result
    )

    # Test 4: Daily aggregation
    run_test(
        "Daily Aggregation - Last Year",
        {'data_type': 'daily', 'days_back': '365'},
        expected_min_rows=0,
        result=result
    )

    # Test 5: Province filter
    run_test(
        "Province Filter - Punjab",
        {'province': 'Punjab', 'days_back': '7'},
        expected_min_rows=0,
        result=result
    )

    # Test 6: City filter
    run_test(
        "City Filter - Lahore",
        {'city': 'Lahore', 'days_back': '7'},
        expected_min_rows=0,
        result=result
    )

    # Test 7: Date range
    run_test(
        "Date Range - 2024",
        {'start_date': '2024-01-01', 'end_date': '2024-12-31', 'data_type': 'daily'},
        expected_min_rows=0,
        result=result
    )

    # Test 8: Combined filters
    run_test(
        "Combined - Punjab + Daily + All Pollutants",
        {'province': 'Punjab', 'data_type': 'daily', 'parameters': 'all', 'days_back': '90'},
        expected_min_rows=0,
        result=result
    )

    # Print summary
    print_header("Test Suite Summary")
    print(f"Total Tests: {result.total}")
    print(f"{Colors.GREEN}Passed: {result.passed}{Colors.NC}")
    if result.failed > 0:
        print(f"{Colors.RED}Failed: {result.failed}{Colors.NC}")
    else:
        print(f"{Colors.GREEN}Failed: {result.failed}{Colors.NC}")

    success_rate = (result.passed / result.total * 100) if result.total > 0 else 0
    print(f"\nSuccess Rate: {success_rate:.1f}%")
    print(f"Test artifacts saved in: {OUTPUT_DIR}")

    if result.failed > 0:
        sys.exit(1)

    print(f"\n{Colors.GREEN}All tests passed! ✓{Colors.NC}")

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Test Hawanama Export API')
    parser.add_argument('--full-historical', action='store_true',
                       help='Run full historical export test (2018-2025)')
    parser.add_argument('--suite', action='store_true',
                       help='Run comprehensive test suite')

    args = parser.parse_args()

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.full_historical:
        success = test_full_historical_export()
        sys.exit(0 if success else 1)
    elif args.suite:
        run_test_suite()
    else:
        # Default: run full historical test
        success = test_full_historical_export()
        sys.exit(0 if success else 1)
