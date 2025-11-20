"""
CSV Export Service for Hawanama Data

This service provides efficient CSV export functionality using PostgreSQL COPY
for large-scale data exports without memory limitations.

Usage:
    from app.services.csv_export_service import CSVExportService
    
    service = CSVExportService()
    
    # Export all station readings
    filepath = service.export_all_station_readings()
    
    # Export specific date range
    filepath = service.export_station_readings_range("2024-01-01", "2024-12-31")
    
    # Export specific city
    filepath = service.export_city_readings("Lahore", days_back=30)
"""

import os
import psycopg2
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)

class CSVExportService:
    """Efficient CSV export service using PostgreSQL COPY for large datasets"""
    
    def __init__(self, export_dir: Optional[Union[str, Path]] = None):
        """
        Initialize CSV export service
        
        Args:
            export_dir: Directory to save CSV files. Defaults to ./exports/
        """
        if export_dir is None:
            export_dir = Path("./exports")
        
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
        # Build database URL from environment
        self.database_url = self._build_database_url()
        
    def _build_database_url(self) -> str:
        """Build PostgreSQL connection URL from environment variables"""
        server = os.getenv('POSTGRES_SERVER')
        user = os.getenv('POSTGRES_USER') 
        password = os.getenv('POSTGRES_PASSWORD')
        db = os.getenv('POSTGRES_DB')
        port = os.getenv('POSTGRES_PORT', '5432')
        
        if not all([server, user, password, db]):
            raise ValueError("Missing required database environment variables")
            
        return f"postgresql://{user}:{password}@{server}:{port}/{db}"
    
    def _get_timestamp(self) -> str:
        """Generate timestamp string for filenames"""
        return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    
    def export_all_station_readings(self) -> Path:
        """
        Export ALL station readings to CSV using PostgreSQL COPY
        
        Returns:
            Path to the generated CSV file
        """
        timestamp = self._get_timestamp()
        filepath = self.export_dir / f"hawanama_station_readings_full_{timestamp}.csv"
        
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
        
        return self._execute_copy_query(query, filepath, "all station readings")
    
    def export_station_readings_range(
        self, 
        start_date: str, 
        end_date: str
    ) -> Path:
        """
        Export station readings for a specific date range
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format (inclusive)
            
        Returns:
            Path to the generated CSV file
        """
        # Validate date format
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # Make end_date inclusive
        except ValueError:
            raise ValueError("Invalid date format. Use YYYY-MM-DD")
        
        timestamp = self._get_timestamp()
        safe_start = start_date.replace('-', '')
        safe_end = end_date.replace('-', '')
        filepath = self.export_dir / f"hawanama_station_readings_{safe_start}_to_{safe_end}_{timestamp}.csv"
        
        query = f"""
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
              AND r.ts_utc >= '{start_dt.isoformat()}'
              AND r.ts_utc < '{end_dt.isoformat()}'
            ORDER BY id, timestamp_utc ASC
        ) TO STDOUT WITH CSV HEADER
        """
        
        return self._execute_copy_query(
            query, 
            filepath, 
            f"station readings from {start_date} to {end_date}"
        )
    
    def export_city_readings(
        self, 
        city_name: str, 
        days_back: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Path:
        """
        Export station readings for a specific city
        
        Args:
            city_name: Name of the city to export
            days_back: Number of days back from now (default: 30)
            start_date: Start date in YYYY-MM-DD format (overrides days_back)
            end_date: End date in YYYY-MM-DD format (requires start_date)
            
        Returns:
            Path to the generated CSV file
        """
        # Determine time range
        if start_date and end_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                date_suffix = f"{start_date.replace('-', '')}_to_{end_date.replace('-', '')}"
            except ValueError:
                raise ValueError("Invalid date format. Use YYYY-MM-DD")
        else:
            if days_back is None:
                days_back = 30
            now = datetime.now(timezone.utc)
            start_dt = now - timedelta(days=days_back)
            end_dt = now
            date_suffix = f"{days_back}days"
        
        timestamp = self._get_timestamp()
        safe_city_name = "".join(c for c in city_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_city_name = safe_city_name.replace(' ', '_')
        filepath = self.export_dir / f"hawanama_station_readings_{safe_city_name}_{date_suffix}_{timestamp}.csv"
        
        query = f"""
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
              AND LOWER(COALESCE(c.name, '')) = LOWER('{city_name}')
              AND r.ts_utc >= '{start_dt.isoformat()}'
              AND r.ts_utc < '{end_dt.isoformat()}'
            ORDER BY id, timestamp_utc ASC
        ) TO STDOUT WITH CSV HEADER
        """
        
        return self._execute_copy_query(
            query, 
            filepath, 
            f"station readings for {city_name}"
        )
    
    def export_pm25_only(
        self,
        city_name: Optional[str] = None,
        days_back: Optional[int] = 30
    ) -> Path:
        """
        Export PM2.5-only readings (streamlined for analysis)
        
        Args:
            city_name: Optional city filter
            days_back: Number of days back from now (default: 30)
            
        Returns:
            Path to the generated CSV file
        """
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=days_back)
        end_dt = now
        
        timestamp = self._get_timestamp()
        
        if city_name:
            safe_city_name = "".join(c for c in city_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_city_name = safe_city_name.replace(' ', '_')
            filepath = self.export_dir / f"hawanama_pm25_{safe_city_name}_{days_back}days_{timestamp}.csv"
            city_filter = f"AND LOWER(COALESCE(c.name, '')) = LOWER('{city_name}')"
        else:
            filepath = self.export_dir / f"hawanama_pm25_all_{days_back}days_{timestamp}.csv"
            city_filter = ""
        
        query = f"""
        COPY (
            SELECT 
                DENSE_RANK() OVER (
                    ORDER BY COALESCE(s.name, 'Unknown Station')
                ) AS id,
                COALESCE(s.name, 'Unknown Station') as station_name,
                COALESCE(s.lat, 0) as latitude,
                COALESCE(s.lon, 0) as longitude,
                COALESCE(c.name, 'Unknown City') as city_name,
                r.ts_utc as timestamp_utc,
                (r.ts_utc + INTERVAL '5 hours') as timestamp_pk,
                CASE WHEN r.pm25 IS NULL THEN 'null' ELSE r.pm25::text END as pm25_ugm3,
                COALESCE(p.code, r.source) as provider_code,
                COALESCE(p.display_name, r.source) as provider_name,
                r.qc_state
            FROM readings r
            LEFT JOIN stations s ON r.scope_key = s.station_id
            LEFT JOIN providers p ON s.provider_id = p.id
            LEFT JOIN cities c ON s.city_id = c.id
            LEFT JOIN states st ON c.state_id = st.id
            LEFT JOIN countries co ON st.country_id = co.id
            WHERE r.scope_type = 'station'
              AND s.active = true
              {city_filter}
              AND r.ts_utc >= '{start_dt.isoformat()}'
              AND r.ts_utc < '{end_dt.isoformat()}'
            ORDER BY id, timestamp_utc ASC
        ) TO STDOUT WITH CSV HEADER
        """
        
        return self._execute_copy_query(
            query, 
            filepath, 
            f"PM2.5 readings{'for ' + city_name if city_name else ' (all cities)'}"
        )
    
    def _execute_copy_query(self, query: str, filepath: Path, description: str) -> Path:
        """
        Execute a COPY query and save results to file
        
        Args:
            query: COPY query to execute
            filepath: Path to save CSV file
            description: Human-readable description for logging
            
        Returns:
            Path to the generated CSV file
        """
        logger.info(f"Starting CSV export: {description}")
        logger.info(f"Output file: {filepath}")
        
        conn = psycopg2.connect(self.database_url)
        try:
            with conn.cursor() as cur, filepath.open("w") as f:
                start_time = datetime.now()
                cur.copy_expert(query, f)
                end_time = datetime.now()
                
                # Get file size for logging
                file_size = filepath.stat().st_size
                file_size_mb = file_size / (1024 * 1024)
                
                logger.info(f"CSV export completed: {description}")
                logger.info(f"File size: {file_size_mb:.2f} MB")
                logger.info(f"Export time: {end_time - start_time}")
                
                return filepath
                
        except Exception as e:
            logger.error(f"CSV export failed: {description}")
            logger.error(f"Error: {str(e)}")
            # Clean up incomplete file
            if filepath.exists():
                filepath.unlink()
            raise
        finally:
            conn.close()


# Convenience functions for direct usage
def export_all_station_readings(export_dir: Optional[Union[str, Path]] = None) -> Path:
    """Export all station readings to CSV"""
    service = CSVExportService(export_dir)
    return service.export_all_station_readings()

def export_station_readings_range(
    start_date: str, 
    end_date: str,
    export_dir: Optional[Union[str, Path]] = None
) -> Path:
    """Export station readings for a date range"""
    service = CSVExportService(export_dir)
    return service.export_station_readings_range(start_date, end_date)

def export_city_readings(
    city_name: str,
    days_back: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    export_dir: Optional[Union[str, Path]] = None
) -> Path:
    """Export station readings for a specific city"""
    service = CSVExportService(export_dir)
    return service.export_city_readings(city_name, days_back, start_date, end_date)

def export_pm25_only(
    city_name: Optional[str] = None,
    days_back: Optional[int] = 30,
    export_dir: Optional[Union[str, Path]] = None
) -> Path:
    """Export PM2.5-only readings"""
    service = CSVExportService(export_dir)
    return service.export_pm25_only(city_name, days_back)


if __name__ == "__main__":
    # Example usage when run directly
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python csv_export_service.py all")
        print("  python csv_export_service.py range 2024-01-01 2024-12-31") 
        print("  python csv_export_service.py city Lahore 30")
        print("  python csv_export_service.py pm25 Lahore 7")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "all":
        filepath = export_all_station_readings()
        print(f"Exported all station readings to: {filepath}")
        
    elif command == "range" and len(sys.argv) >= 4:
        start_date = sys.argv[2]
        end_date = sys.argv[3]
        filepath = export_station_readings_range(start_date, end_date)
        print(f"Exported station readings ({start_date} to {end_date}) to: {filepath}")
        
    elif command == "city" and len(sys.argv) >= 4:
        city_name = sys.argv[2]
        days_back = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        filepath = export_city_readings(city_name, days_back=days_back)
        print(f"Exported {city_name} station readings ({days_back} days) to: {filepath}")
        
    elif command == "pm25":
        city_name = sys.argv[2] if len(sys.argv) > 2 else None
        days_back = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        filepath = export_pm25_only(city_name, days_back)
        print(f"Exported PM2.5 readings to: {filepath}")
        
    else:
        print("Invalid command or arguments")
        sys.exit(1)