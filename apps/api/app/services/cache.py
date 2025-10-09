# app/services/cache.py
import logging, os, json
from typing import Any, Optional

log = logging.getLogger(__name__)

class _NullCache:
    def get(self, *_a, **_k): return None
    def setex(self, *_a, **_k): return
    def set(self, *_a, **_k): return

_cache = None

def get_cache():
    global _cache
    if _cache is not None:
        return _cache

    backend = (os.getenv("CACHE_BACKEND") or "").lower()  # "redis" | "upstash" | ""
    if backend == "upstash":
        try:
            from upstash_redis import Redis as UpstashRedis
            _cache = UpstashRedis(
                url=os.environ["UPSTASH_REDIS_REST_URL"],
                token=os.environ["UPSTASH_REDIS_REST_TOKEN"],
            )
            log.info("Upstash cache initialized")
            return _cache
        except Exception as e:
            log.warning("Upstash disabled: %s", e)

    if backend == "redis":
        try:
            import redis
            url = os.getenv("REDIS_URL")
            if url:
                _cache = redis.from_url(url, decode_responses=True)
                log.info("Redis cache initialized from URL")
                return _cache
            host = os.getenv("REDIS_HOST")
            if host:
                _cache = redis.Redis(
                    host=host,
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    password=os.getenv("REDIS_PASSWORD") or None,
                    decode_responses=True,
                )
                log.info("Redis cache initialized from host/port")
                return _cache
        except Exception as e:
            log.warning("Redis disabled: %s", e)

    log.info("Using null cache (no caching)")
    _cache = _NullCache()
    return _cache

cache = get_cache()