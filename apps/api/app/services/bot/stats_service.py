"""
Monthly Statistics Service for Hawanama Bot

Analyzes historical PAQI data from CSV to provide monthly context statistics
including 95th percentile AQI and all-time high daily AQI for each month.
"""

import logging
import csv
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Default timezone (PKT / Asia/Karachi)
TZ = ZoneInfo("Asia/Karachi")


class MonthlyStatsService:
    """Service for analyzing monthly air quality statistics from historical CSV data"""
    
    def __init__(self, csv_file_path: Optional[str] = None):
        """
        Initialize the MonthlyStatsService.
        
        Args:
            csv_file_path: Path to the CSV file containing monthly statistics
                          If None, uses the default external_data location
        """
        if csv_file_path:
            self.csv_file_path = Path(csv_file_path)
        else:
            # Default path relative to the API directory
            # From apps/api/app/services/ -> go up to hawanama-main/external_data/
            api_dir = Path(__file__).parent.parent.parent.parent.parent
            self.csv_file_path = api_dir / "external_data" / "lahore_monthly_summary_2017_2025.csv"
        
        self._monthly_data: Optional[Dict[str, Dict[str, float]]] = None
        
    def _load_csv_data(self) -> Dict[str, Dict[str, float]]:
        """
        Load monthly statistics from CSV file.
        
        Returns:
            Dict mapping month names to their statistics
            
        Raises:
            FileNotFoundError: If CSV file doesn't exist
            ValueError: If CSV data is malformed
        """
        if not self.csv_file_path.exists():
            raise FileNotFoundError(f"Monthly stats CSV not found: {self.csv_file_path}")
        
        monthly_data = {}
        
        try:
            with open(self.csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    month_name = row['month_name'].strip()
                    
                    # Extract the required statistics
                    # AQI_95th -> p95_daily_aqi
                    # hourly_peak_aqi_value -> allTimeHigh_daily_aqi (use hourly peak as true all-time high)
                    try:
                        p95_daily_aqi = float(row['AQI_95th'])
                        all_time_high_daily_aqi = float(row['hourly_peak_aqi_value'])
                        
                        monthly_data[month_name] = {
                            'p95_daily_aqi': int(round(p95_daily_aqi)),
                            'allTimeHigh_daily_aqi': int(round(all_time_high_daily_aqi))
                        }
                        
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Error parsing data for {month_name}: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"Failed to load monthly statistics CSV: {e}")
            raise ValueError(f"Failed to parse monthly statistics CSV: {e}")
        
        if not monthly_data:
            raise ValueError("No valid monthly data found in CSV")
            
        logger.info(f"Loaded monthly statistics for {len(monthly_data)} months")
        return monthly_data
    
    def get_monthly_context(self, month_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get monthly statistical context for the specified month.
        
        Args:
            month_name: Name of the month (e.g., "November"). If None, uses current month.
            
        Returns:
            Dict containing month name, p95_daily_aqi, and allTimeHigh_daily_aqi
        """
        # Load data if not already cached
        if self._monthly_data is None:
            try:
                self._monthly_data = self._load_csv_data()
            except Exception as e:
                logger.error(f"Failed to load monthly data: {e}")
                # Return fallback data
                return self._get_fallback_data(month_name)
        
        # Determine target month
        if month_name is None:
            month_name = datetime.now(TZ).strftime("%B")
        
        # Get statistics for the month
        month_stats = self._monthly_data.get(month_name)
        
        if month_stats is None:
            logger.warning(f"No data found for month: {month_name}")
            return self._get_fallback_data(month_name)
        
        return {
            "monthName": month_name,
            "p95_daily_aqi": month_stats["p95_daily_aqi"],
            "allTimeHigh_daily_aqi": month_stats["allTimeHigh_daily_aqi"]
        }
    
    def _get_fallback_data(self, month_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Provide fallback data when CSV loading fails.
        
        Args:
            month_name: Target month name
            
        Returns:
            Dict with fallback monthly statistics
        """
        if month_name is None:
            month_name = datetime.now(TZ).strftime("%B")
        
        # Fallback to reasonable estimates based on season
        seasonal_fallback = {
            "January": {"p95_daily_aqi": 400, "allTimeHigh_daily_aqi": 557},
            "February": {"p95_daily_aqi": 326, "allTimeHigh_daily_aqi": 291},
            "March": {"p95_daily_aqi": 242, "allTimeHigh_daily_aqi": 219},
            "April": {"p95_daily_aqi": 210, "allTimeHigh_daily_aqi": 225},
            "May": {"p95_daily_aqi": 198, "allTimeHigh_daily_aqi": 213},
            "June": {"p95_daily_aqi": 180, "allTimeHigh_daily_aqi": 268},
            "July": {"p95_daily_aqi": 181, "allTimeHigh_daily_aqi": 199},
            "August": {"p95_daily_aqi": 168, "allTimeHigh_daily_aqi": 173},
            "September": {"p95_daily_aqi": 190, "allTimeHigh_daily_aqi": 191},
            "October": {"p95_daily_aqi": 392, "allTimeHigh_daily_aqi": 483},
            "November": {"p95_daily_aqi": 464, "allTimeHigh_daily_aqi": 521},
            "December": {"p95_daily_aqi": 449, "allTimeHigh_daily_aqi": 447}
        }
        
        stats = seasonal_fallback.get(month_name, {"p95_daily_aqi": 350, "allTimeHigh_daily_aqi": 450})
        
        return {
            "monthName": month_name,
            "p95_daily_aqi": stats["p95_daily_aqi"],
            "allTimeHigh_daily_aqi": stats["allTimeHigh_daily_aqi"]
        }
    
    def get_all_months_data(self) -> Dict[str, Dict[str, Any]]:
        """
        Get statistics for all months.
        
        Returns:
            Dict mapping month names to their statistics
        """
        if self._monthly_data is None:
            try:
                self._monthly_data = self._load_csv_data()
            except Exception as e:
                logger.error(f"Failed to load monthly data: {e}")
                return {}
        
        result = {}
        for month_name, stats in self._monthly_data.items():
            result[month_name] = {
                "monthName": month_name,
                "p95_daily_aqi": stats["p95_daily_aqi"],
                "allTimeHigh_daily_aqi": stats["allTimeHigh_daily_aqi"]
            }
        
        return result
    
    def validate_data_integrity(self) -> Dict[str, Any]:
        """
        Validate the integrity of the loaded monthly data.
        
        Returns:
            Dict with validation results
        """
        try:
            data = self._load_csv_data() if self._monthly_data is None else self._monthly_data
            
            expected_months = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ]
            
            missing_months = [month for month in expected_months if month not in data]
            
            # Validate data ranges
            validation_issues = []
            for month, stats in data.items():
                p95 = stats.get("p95_daily_aqi", 0)
                peak = stats.get("allTimeHigh_daily_aqi", 0)
                
                if p95 < 0 or p95 > 1500:
                    validation_issues.append(f"{month}: p95_daily_aqi out of range ({p95})")
                
                if peak < 0 or peak > 1500:
                    validation_issues.append(f"{month}: allTimeHigh_daily_aqi out of range ({peak})")
                
                if peak < p95:
                    validation_issues.append(f"{month}: peak AQI ({peak}) lower than p95 AQI ({p95})")
            
            return {
                "valid": len(missing_months) == 0 and len(validation_issues) == 0,
                "months_loaded": len(data),
                "missing_months": missing_months,
                "validation_issues": validation_issues,
                "csv_file_path": str(self.csv_file_path),
                "csv_exists": self.csv_file_path.exists()
            }
            
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "csv_file_path": str(self.csv_file_path),
                "csv_exists": self.csv_file_path.exists()
            }


# Global instance for use across the application
monthly_stats_service = MonthlyStatsService()