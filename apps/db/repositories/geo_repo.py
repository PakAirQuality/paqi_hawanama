"""
Geographic data repository
Handles queries for countries, states, cities, and geographic hierarchies
"""

import logging
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def list_cities_in_country(session: AsyncSession, country: str) -> List[Dict[str, Any]]:
    """
    Get all cities in a country with their full geographic context
    
    Args:
        session: Database session
        country: Country name (e.g., "Pakistan")
    
    Returns:
        List of city rows with country, state, city, city_id, and canonical scope_key
    """
    try:
        query = text("""
            SELECT 
                c.id as city_id,
                co.name as country,
                s.name as state, 
                c.name as city,
                CONCAT(LOWER(co.name), '|', LOWER(s.name), '|', LOWER(c.name)) as scope_key
            FROM cities c
            LEFT JOIN countries co ON c.country_id = co.id
            LEFT JOIN states s ON c.state_id = s.id  
            WHERE co.name = :country 
              AND c.active = TRUE
              AND co.active = TRUE
              AND s.active = TRUE
            ORDER BY s.name, c.name
        """)
        
        result = await session.execute(query, {"country": country})
        cities = [dict(row._mapping) for row in result.fetchall()]
        
        logger.debug(f"Found {len(cities)} active cities in {country}")
        return cities
        
    except Exception as error:
        logger.error(f"Failed to fetch cities for country {country}: {error}")
        return []


async def get_city_by_scope_key(session: AsyncSession, scope_key: str) -> Dict[str, Any]:
    """
    Get a city by its scope key (e.g., "pakistan|punjab|lahore")
    
    Args:
        session: Database session
        scope_key: Canonical scope key
    
    Returns:
        City row with geographic context or empty dict if not found
    """
    try:
        # Parse scope key - format: "country|state|city"
        parts = scope_key.lower().split('|')
        if len(parts) != 3:
            logger.warning(f"Invalid scope key format: {scope_key}")
            return {}
            
        country, state, city = parts
        
        query = text("""
            SELECT 
                c.id as city_id,
                co.name as country,
                s.name as state, 
                c.name as city,
                :scope_key as scope_key,
                c.timezone,
                ST_Y(ST_Centroid(c.geom)) as latitude,
                ST_X(ST_Centroid(c.geom)) as longitude
            FROM cities c
            LEFT JOIN countries co ON c.country_id = co.id
            LEFT JOIN states s ON c.state_id = s.id  
            WHERE LOWER(co.name) = :country 
              AND LOWER(s.name) = :state
              AND LOWER(c.name) = :city
              AND c.active = TRUE
              AND co.active = TRUE
              AND s.active = TRUE
        """)
        
        result = await session.execute(query, {
            "scope_key": scope_key,
            "country": country,
            "state": state, 
            "city": city
        })
        
        city_row = result.fetchone()
        if city_row:
            return dict(city_row._mapping)
        else:
            logger.debug(f"City not found for scope key: {scope_key}")
            return {}
        
    except Exception as error:
        logger.error(f"Failed to fetch city by scope key {scope_key}: {error}")
        return {}


async def get_cities_by_state(session: AsyncSession, country: str, state: str) -> List[Dict[str, Any]]:
    """
    Get all cities in a specific state
    
    Args:
        session: Database session
        country: Country name
        state: State name
    
    Returns:
        List of city rows in the state
    """
    try:
        query = text("""
            SELECT 
                c.id as city_id,
                co.name as country,
                s.name as state, 
                c.name as city,
                CONCAT(LOWER(co.name), '|', LOWER(s.name), '|', LOWER(c.name)) as scope_key
            FROM cities c
            LEFT JOIN countries co ON c.country_id = co.id
            LEFT JOIN states s ON c.state_id = s.id  
            WHERE co.name = :country 
              AND s.name = :state
              AND c.active = TRUE
              AND co.active = TRUE
              AND s.active = TRUE
            ORDER BY c.name
        """)
        
        result = await session.execute(query, {
            "country": country,
            "state": state
        })
        
        cities = [dict(row._mapping) for row in result.fetchall()]
        logger.debug(f"Found {len(cities)} cities in {state}, {country}")
        return cities
        
    except Exception as error:
        logger.error(f"Failed to fetch cities for {state}, {country}: {error}")
        return []


async def get_country_stats(session: AsyncSession, country: str) -> Dict[str, Any]:
    """
    Get statistics for a country (states, cities, stations counts)
    
    Args:
        session: Database session
        country: Country name
    
    Returns:
        Dictionary with country statistics
    """
    try:
        query = text("""
            SELECT 
                co.name as country,
                COUNT(DISTINCT s.id) as total_states,
                COUNT(DISTINCT c.id) as total_cities,
                COUNT(DISTINCT st.station_id) as total_stations,
                COUNT(DISTINCT CASE WHEN st.active = TRUE THEN st.station_id END) as active_stations
            FROM countries co
            LEFT JOIN states s ON co.id = s.country_id AND s.active = TRUE
            LEFT JOIN cities c ON co.id = c.country_id AND c.active = TRUE  
            LEFT JOIN stations st ON co.id = st.country_id
            WHERE co.name = :country
              AND co.active = TRUE
            GROUP BY co.name
        """)
        
        result = await session.execute(query, {"country": country})
        stats = result.fetchone()
        
        if stats:
            return dict(stats._mapping)
        else:
            return {
                "country": country,
                "total_states": 0,
                "total_cities": 0, 
                "total_stations": 0,
                "active_stations": 0
            }
        
    except Exception as error:
        logger.error(f"Failed to fetch country stats for {country}: {error}")
        return {
            "country": country,
            "error": str(error)
        }