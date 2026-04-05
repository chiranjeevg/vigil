"""Simple in-memory cache for frequently accessed data."""

import asyncio
import time
from functools import wraps
from typing import Any, Optional


class SimpleCache:
    """Thread-safe in-memory cache with TTL."""

    def __init__(self, default_ttl: int = 5):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from cache if not expired."""
        if key in self._cache:
            value, expires_at = self._cache[key]
            if time.time() < expires_at:
                return value
            async with self._lock:
                self._cache.pop(key, None)
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in cache with TTL."""
        ttl = ttl or self._default_ttl
        async with self._lock:
            self._cache[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all cached values."""
        async with self._lock:
            self._cache.clear()

    def invalidate_pattern(self, pattern: str) -> None:
        """Invalidate all keys matching a pattern (sync version for convenience)."""
        keys_to_delete = [k for k in self._cache.keys() if pattern in k]
        for key in keys_to_delete:
            self._cache.pop(key, None)


# Global cache instance
_cache = SimpleCache(default_ttl=5)


def get_cache() -> SimpleCache:
    """Get the global cache instance."""
    return _cache


def cached(ttl: int = 5, key_prefix: str = ""):
    """Decorator for caching async function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{func.__name__}:{hash(str(args) + str(kwargs))}"

            cached_value = await _cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            result = await func(*args, **kwargs)
            await _cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
