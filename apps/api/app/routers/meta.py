from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_database
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)
# Updated with new metadata endpoints
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
    """The one PM2.5 / US AQI category table every client renders from.

    `categories` is the canonical list (key, label, pm25_max, aqi range, colours);
    `us_epa` keeps the older object shape the public site's client still parses,
    generated from the same table so colours and ranges cannot drift.
    """
    from app.services.aqi.pm25 import categories_payload

    payload = categories_payload()
    legacy_keys = {"unhealthy_sensitive": "unhealthy_for_sensitive_groups"}
    payload["us_epa"] = {
        legacy_keys.get(b["key"], b["key"]): {
            "range": [b["aqi_min"], b["aqi_max"]],
            "pm25_max": b["pm25_max"],
            "color": b["color"],
            "text_color": b["text_color"],
            "description": b["description"],
        }
        for b in payload["categories"]
    }
    return payload

@router.get("/countries")
async def get_countries(
    db: AsyncSession = Depends(get_database)
) -> List[str]:
    """Get list of countries with station data for scrollable selection"""
    try:
        query = """
        SELECT DISTINCT c.name as country_name
        FROM countries c
        INNER JOIN states s ON c.id = s.country_id
        INNER JOIN stations st ON s.id = st.state_id
        WHERE c.active = true AND s.active = true AND st.active = true
        ORDER BY c.name
        """
        
        result = await db.execute(text(query))
        rows = result.fetchall()
        
        countries = [row.country_name for row in rows]
        logger.info(f"Retrieved {len(countries)} countries with station data")
        return countries
        
    except Exception as e:
        logger.error(f"Error getting countries: {e}")
        return []

@router.get("/provinces")
async def get_provinces(
    country_name: Optional[str] = None,
    db: AsyncSession = Depends(get_database)
) -> List[str]:
    """Get scrollable list of provinces/states with station data. If no country_name provided, shows all provinces for selection."""
    try:
        # Get provinces/states that have active stations
        query = """
        SELECT DISTINCT s.name as province_name, c.name as country_name
        FROM states s
        INNER JOIN countries c ON s.country_id = c.id
        INNER JOIN stations st ON st.state_id = s.id
        WHERE s.active = true AND st.active = true AND c.active = true
        """
        params = {}
        
        if country_name:
            query += " AND LOWER(c.name) = LOWER(:country_name)"
            params["country_name"] = country_name
        # If no country_name provided, show all provinces for scrollable selection
            
        query += " ORDER BY c.name, s.name"
        
        result = await db.execute(text(query), params)
        rows = result.fetchall()
        
        if country_name:
            # Return just province names when filtering by country
            provinces = [row.province_name for row in rows]
            logger.info(f"Retrieved {len(provinces)} provinces for country: {country_name}")
            return provinces
        else:
            # Return formatted list showing country and province for scrollable selection
            provinces = [f"{row.province_name}, {row.country_name}" for row in rows]
            logger.info(f"Retrieved {len(provinces)} provinces across all countries for selection")
            return provinces
        
    except Exception as e:
        logger.error(f"Error getting provinces: {e}")
        return []

@router.get("/cities")
async def get_cities(
    province_name: Optional[str] = None,
    country_name: Optional[str] = None,
    province: Optional[str] = None,
    country: Optional[str] = None,
    db: AsyncSession = Depends(get_database)
) -> List[str]:
    """Get scrollable list of cities with station data. If no province_name provided, shows all cities for selection.
    `province`/`country` are accepted as aliases (the dashboard used them and was silently unfiltered).
    The province filter applies to the station's own state as well as the city's, so a city
    row attached to the wrong state cannot leak into another province's list."""
    province_name = province_name or province
    country_name = country_name or country
    try:
        # Get cities that have active stations
        query = """
        SELECT DISTINCT c.name as city_name, s.name as province_name, co.name as country_name
        FROM cities c
        INNER JOIN states s ON c.state_id = s.id
        INNER JOIN countries co ON c.country_id = co.id
        INNER JOIN stations st ON st.city_id = c.id
        WHERE c.active = true AND s.active = true AND co.active = true AND st.active = true
        """
        params = {}

        if province_name:
            query += " AND LOWER(s.name) = LOWER(:province_name) AND st.state_id = s.id"
            params["province_name"] = province_name
        if country_name:
            query += " AND LOWER(co.name) = LOWER(:country_name)"
            params["country_name"] = country_name
        # If no province_name provided, show all cities for scrollable selection
            
        query += " ORDER BY co.name, s.name, c.name"
        
        result = await db.execute(text(query), params)
        rows = result.fetchall()
        
        if province_name:
            # Return just city names when filtering by province
            cities = [row.city_name for row in rows]
            logger.info(f"Retrieved {len(cities)} cities for province: {province_name}")
            return cities
        else:
            # Return formatted list showing city, province, country for scrollable selection
            cities = [f"{row.city_name}, {row.province_name}, {row.country_name}" for row in rows]
            logger.info(f"Retrieved {len(cities)} cities across all provinces for selection")
            return cities
        
    except Exception as e:
        logger.error(f"Error getting cities for province {province_name}: {e}")
        return []

@router.get("/stations")
async def get_stations(
    province_name: Optional[str] = None,
    city_name: Optional[str] = None,
    province: Optional[str] = None,
    city: Optional[str] = None,
    db: AsyncSession = Depends(get_database)
) -> List[Dict[str, str]]:
    """Get scrollable list of stations with station_id and station_name. If no filters provided, shows all stations for selection.
    `city`/`province` are accepted as aliases of `city_name`/`province_name` (runbooks used them and were silently ignored)."""
    province_name = province_name or province
    city_name = city_name or city
    try:
        # Get stations with their metadata - same pattern as cities/{city}/current endpoint
        query = """
        SELECT 
            st.station_id as station_id,
            st.name as station_name,
            c.name as city_name,
            s.name as province_name,
            co.name as country_name
        FROM stations st
        INNER JOIN cities c ON st.city_id = c.id
        INNER JOIN states s ON st.state_id = s.id
        INNER JOIN countries co ON c.country_id = co.id
        WHERE st.active = true AND c.active = true AND s.active = true AND co.active = true
          AND COALESCE(st.metadata_json->'registry'->>'status', 'active') <> 'test'
        """
        params = {}

        if province_name:
            query += " AND LOWER(s.name) = LOWER(:province_name)"
            params["province_name"] = province_name

        if city_name:
            query += " AND LOWER(c.name) = LOWER(:city_name)"
            params["city_name"] = city_name
            
        query += " ORDER BY co.name, s.name, c.name, st.name"
        
        result = await db.execute(text(query), params)
        rows = result.fetchall()
        
        if province_name or city_name:
            # Return basic station info when filtering
            stations = [
                {
                    "station_id": row.station_id,
                    "station_name": row.station_name
                } 
                for row in rows
            ]
        else:
            # Return detailed info for scrollable selection
            stations = [
                {
                    "station_id": row.station_id,
                    "station_name": row.station_name,
                    "display_name": f"{row.station_name}, {row.city_name}, {row.province_name}, {row.country_name}"
                } 
                for row in rows
            ]
        
        logger.info(f"Retrieved {len(stations)} stations for province: {province_name or 'all'}, city: {city_name or 'all'}")
        return stations
        
    except Exception as e:
        logger.error(f"Error getting stations for province {province_name}, city {city_name}: {e}")
        return []