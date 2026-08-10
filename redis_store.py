"""Small, lazy Redis client helper."""

from functools import lru_cache

try:
    import redis
except ImportError:  # Redis is optional for development fallback mode.
    redis = None

import config


class RedisUnavailableError(RuntimeError):
    """Raised when the optional Redis client is not installed."""


@lru_cache(maxsize=1)
def get_redis():
    """Return the shared Redis client; connection is established on use."""
    if redis is None:
        raise RedisUnavailableError("The redis package is not installed")
    return redis.Redis.from_url(config.REDIS_URL, decode_responses=True)


def clear_redis_cache() -> None:
    """Reset the cached client, useful in tests and configuration reloads."""
    get_redis.cache_clear()
