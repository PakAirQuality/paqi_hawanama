from fastapi import APIRouter
from typing import Dict, List, Any

router = APIRouter()

@router.get("/aqi-scales")
async def get_aqi_scales() -> Dict[str, Any]:
    """Get available AQI scales"""
    return {
        "scales": ["us", "cn"],
        "description": {
            "us": "US EPA AQI scale (0-500)",
            "cn": "China MEP AQI scale (0-500)"
        },
        "default": "us"
    }

@router.get("/pollutants")
async def get_pollutants() -> Dict[str, Any]:
    """Get pollutant information and aliases"""
    return {
        "aliases": {
            "p1": "pm10",
            "p2": "pm25", 
            "o3": "ozone",
            "n2": "no2",
            "s2": "so2",
            "co": "carbon_monoxide"
        },
        "pollutants": {
            "pm25": {
                "name": "Particulate Matter 2.5",
                "symbol": "PM₂.₅",
                "unit": "µg/m³",
                "description": "Fine particulate matter with diameter less than 2.5 micrometers"
            },
            "pm10": {
                "name": "Particulate Matter 10",
                "symbol": "PM₁₀", 
                "unit": "µg/m³",
                "description": "Coarse particulate matter with diameter less than 10 micrometers"
            },
            "ozone": {
                "name": "Ground-level Ozone",
                "symbol": "O₃",
                "unit": "µg/m³",
                "description": "Ground-level ozone gas"
            },
            "no2": {
                "name": "Nitrogen Dioxide",
                "symbol": "NO₂",
                "unit": "µg/m³", 
                "description": "Nitrogen dioxide gas"
            },
            "so2": {
                "name": "Sulfur Dioxide",
                "symbol": "SO₂",
                "unit": "µg/m³",
                "description": "Sulfur dioxide gas"
            },
            "carbon_monoxide": {
                "name": "Carbon Monoxide",
                "symbol": "CO",
                "unit": "mg/m³",
                "description": "Carbon monoxide gas"
            }
        }
    }

@router.get("/units")
async def get_units() -> Dict[str, Any]:
    """Get canonical units for measurements"""
    return {
        "pollutants": {
            "pm25": "µg/m³",
            "pm10": "µg/m³", 
            "ozone": "µg/m³",
            "no2": "µg/m³",
            "so2": "µg/m³",
            "carbon_monoxide": "mg/m³"
        },
        "meteorological": {
            "temperature": "°C",
            "humidity": "%",
            "pressure": "hPa",
            "wind_speed": "m/s",
            "wind_direction": "degrees",
            "heat_index": "°C"
        },
        "air_quality": {
            "aqi": "index (0-500)",
            "aqi_category": "text"
        },
        "coordinates": {
            "latitude": "decimal degrees",
            "longitude": "decimal degrees"
        },
        "time": {
            "timestamp": "ISO 8601 (UTC)",
            "timezone": "UTC"
        }
    }

@router.get("/aqi-categories")
async def get_aqi_categories() -> Dict[str, Any]:
    """Get AQI category definitions"""
    return {
        "us_epa": {
            "good": {
                "range": [0, 50],
                "color": "#00E400",
                "description": "Air quality is considered satisfactory"
            },
            "moderate": {
                "range": [51, 100], 
                "color": "#FFFF00",
                "description": "Air quality is acceptable for most people"
            },
            "unhealthy_for_sensitive_groups": {
                "range": [101, 150],
                "color": "#FF7E00", 
                "description": "Sensitive individuals may experience health effects"
            },
            "unhealthy": {
                "range": [151, 200],
                "color": "#FF0000",
                "description": "Everyone may begin to experience health effects"
            },
            "very_unhealthy": {
                "range": [201, 300],
                "color": "#8F3F97",
                "description": "Health warnings of emergency conditions"
            },
            "hazardous": {
                "range": [301, 500],
                "color": "#7E0023",
                "description": "Health alert: everyone may experience serious health effects"
            }
        }
    }