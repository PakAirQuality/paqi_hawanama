#!/usr/bin/env python3
"""
Standalone CSV export script for Hawanama data

This script exports all station readings to CSV format using PostgreSQL COPY.
Run from the project root directory.

Usage:
    python scripts/export_all_csv.py
"""

import os
import sys
import psycopg2
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Alternative: load from apps/api/.env
api_env_path = Path(__file__).parent.parent / 'apps/api/.env'
if api_env_path.exists():
    load_dotenv(api_env_path)

def get_database_url():
    """Build PostgreSQL connection URL from environment variables"""
    server = os.getenv('POSTGRES_SERVER')
    user = os.getenv('POSTGRES_USER') 
    password = os.getenv('POSTGRES_PASSWORD')
    db = os.getenv('POSTGRES_DB')
    port = os.getenv('POSTGRES_PORT', '5432')
    
    print(f"Database config:")
    print(f"  Server: {server}")
    print(f"  User: {user}")
    print(f"  Database: {db}")
    print(f"  Port: {port}")
    
    if not all([server, user, password, db]):
        print("ERROR: Missing required database environment variables")
        print("Make sure .env file exists with POSTGRES_* variables")
        return None
        
    return f"postgresql://{user}:{password}@{server}:{port}/{db}"

def export_all_station_readings():
    """Export all station readings to CSV using PostgreSQL COPY"""
    
    # Setup
    database_url = get_database_url()
    if not database_url:
        return None
        
    export_dir = Path("./exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filepath = export_dir / f"hawanama_station_readings_full_{timestamp}.csv"
    
    # SQL query with COPY
    query = """
    COPY (
        SELECT 
            DENSE_RANK() OVER (
                ORDER BY COALESCE(s.name, 'Unknown Station')
            ) AS id,
            COALESCE(s.name, 'Unknown Station') as station_name,
            COALESCE(s.lat, 0) as latitude,
            COALESCE(s.lon, 0) as longitude,
            COALESCE(c.name, 'Unknown City') as city_name,
            COALESCE(st.name, 'Unknown State') as state_name,
            COALESCE(co.name, 'Unknown Country') as country_name,
            r.ts_utc as timestamp_utc,
            r.pm25 as pm25_ugm3,
            r.aqi_us,
            r.aqi_cn,
            r.main_us as main_pollutant_us,
            r.main_cn as main_pollutant_cn,
            r.temp_c as temperature_celsius,
            r.humidity as humidity_percent,
            r.pressure_hpa,
            r.wind_speed_ms,
            r.wind_dir_deg as wind_direction_degrees,
            r.heatindex_c as heat_index_celsius,
            r.weather_icon,
            r.qc_state,
            COALESCE(p.code, r.source) as provider_code,
            COALESCE(p.display_name, r.source) as provider_name,
            COALESCE(r.units_pm25, 'µg/m³') as pm25_units
        FROM readings r
        LEFT JOIN stations s ON r.scope_key = s.station_id
        LEFT JOIN providers p ON s.provider_id = p.id
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON c.state_id = st.id
        LEFT JOIN countries co ON st.country_id = co.id
        WHERE r.scope_type = 'station'
          AND s.active = true
        ORDER BY id, timestamp_utc ASC
    ) TO STDOUT WITH CSV HEADER
    """
    
    print(f"Starting export to: {filepath}")
    print(f"Connecting to database...")
    
    try:
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur, filepath.open("w") as f:
                start_time = datetime.now()
                print(f"Executing COPY query...")
                cur.copy_expert(query, f)
                end_time = datetime.now()
                
                # Get file size for reporting
                file_size = filepath.stat().st_size
                file_size_mb = file_size / (1024 * 1024)
                
                print(f"✅ Export completed successfully!")
                print(f"📁 File: {filepath}")
                print(f"📊 Size: {file_size_mb:.2f} MB")
                print(f"⏱️  Time: {end_time - start_time}")
                
                # Show first few lines
                print(f"\n📋 First 3 lines:")
                with filepath.open("r") as f:
                    for i, line in enumerate(f):
                        if i < 3:
                            print(f"   {line.strip()}")
                        else:
                            break
                
                return filepath
                
        except Exception as e:
            print(f"❌ Export failed: {str(e)}")
            # Clean up incomplete file
            if filepath.exists():
                filepath.unlink()
            return None
        finally:
            conn.close()
            
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)}")
        return None

if __name__ == "__main__":
    print("🚀 Hawanama CSV Export - All Station Readings")
    print("=" * 50)
    
    result = export_all_station_readings()
    
    if result:
        print(f"\n🎉 Success! CSV exported to: {result}")
    else:
        print(f"\n💥 Export failed!")
        sys.exit(1)