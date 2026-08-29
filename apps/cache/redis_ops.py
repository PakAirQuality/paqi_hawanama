"""
Redis cache operations
Handles cache invalidation and management for city data
"""

import logging
import redis.asyncio as redis
from typing import List
from config.settings import settings

logger = logging.getLogger(__name__)


async def bust_city_keys(scope_keys: List[str]):
    """
    Bust cache keys for updated cities
    
    Args:
        scope_keys: List of city scope keys that were updated
    """
    if not scope_keys:
        return
    
    try:
        # Create Redis connection
        redis_client = redis.from_url(settings.REDIS_URL)
        
        # Generate cache key patterns for each scope
        cache_keys = []
        for scope_key in scope_keys:
            # Common cache key patterns for city data
            cache_keys.extend([
                f"city:current:{scope_key}",
                f"city:history:{scope_key}",
                f"city:forecast:{scope_key}",
                f"city:summary:{scope_key}",
                f"api:city:{scope_key}:*",  # Pattern for API responses
                f"readings:{scope_key}:*",   # Pattern for readings cache
            ])
        
        # Also bust aggregated cache keys
        country_states = set()
        for scope_key in scope_keys:
            parts = scope_key.split('|')
            if len(parts) >= 2:
                country_states.add(f"{parts[0]}|{parts[1]}")  # country|state
        
        for country_state in country_states:
            cache_keys.extend([
                f"state:cities:{country_state}",
                f"state:summary:{country_state}",
            ])
        
        # Delete cache keys in batches
        if cache_keys:
            # For pattern-based keys, use SCAN and delete
            pattern_keys = [k for k in cache_keys if '*' in k]
            direct_keys = [k for k in cache_keys if '*' not in k]
            
            # Delete direct keys
            if direct_keys:
                deleted_direct = await redis_client.delete(*direct_keys)
                logger.debug(f"Deleted {deleted_direct} direct cache keys")
            
            # Delete pattern keys
            for pattern_key in pattern_keys:
                keys_to_delete = []
                async for key in redis_client.scan_iter(match=pattern_key):
                    keys_to_delete.append(key)
                
                if keys_to_delete:
                    deleted_pattern = await redis_client.delete(*keys_to_delete)
                    logger.debug(f"Deleted {deleted_pattern} cache keys matching pattern: {pattern_key}")
        
        await redis_client.close()
        
        logger.info(f"Cache busted for {len(scope_keys)} city scope keys")
        
    except Exception as error:
        logger.warning(f"Cache bust failed: {error}")
        # Don't raise - cache bust failure shouldn't stop the ingestion


async def bust_all_city_cache():
    """
    Clear all city-related cache (use sparingly)
    """
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        
        # Patterns for all city-related cache
        patterns = [
            "city:*",
            "state:*", 
            "api:city:*",
            "readings:*",
            "forecast:*"
        ]
        
        total_deleted = 0
        for pattern in patterns:
            keys_to_delete = []
            async for key in redis_client.scan_iter(match=pattern):
                keys_to_delete.append(key)
            
            if keys_to_delete:
                deleted = await redis_client.delete(*keys_to_delete)
                total_deleted += deleted
                logger.debug(f"Deleted {deleted} keys matching pattern: {pattern}")
        
        await redis_client.close()
        
        logger.info(f"Total cache bust: deleted {total_deleted} keys")
        return total_deleted
        
    except Exception as error:
        logger.error(f"Full cache bust failed: {error}")
        return 0


async def set_city_cache(scope_key: str, cache_type: str, data: dict, ttl_seconds: int = 3600):
    """
    Set cache data for a city
    
    Args:
        scope_key: City scope key
        cache_type: Type of cache (current, history, forecast, summary)
        data: Data to cache
        ttl_seconds: Time to live in seconds
    """
    try:
        import json
        
        redis_client = redis.from_url(settings.REDIS_URL)
        
        cache_key = f"city:{cache_type}:{scope_key}"
        serialized_data = json.dumps(data, default=str)
        
        await redis_client.setex(cache_key, ttl_seconds, serialized_data)
        await redis_client.close()
        
        logger.debug(f"Cached {cache_type} data for {scope_key}")
        
    except Exception as error:
        logger.warning(f"Failed to set cache for {scope_key}: {error}")


async def get_city_cache(scope_key: str, cache_type: str) -> dict:
    """
    Get cached data for a city
    
    Args:
        scope_key: City scope key
        cache_type: Type of cache to retrieve
    
    Returns:
        Cached data dictionary or empty dict if not found
    """
    try:
        import json
        
        redis_client = redis.from_url(settings.REDIS_URL)
        
        cache_key = f"city:{cache_type}:{scope_key}"
        cached_data = await redis_client.get(cache_key)
        await redis_client.close()
        
        if cached_data:
            return json.loads(cached_data)
        else:
            return {}
        
    except Exception as error:
        logger.debug(f"Failed to get cache for {scope_key}: {error}")
        return {}