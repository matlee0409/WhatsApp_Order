"""Small, lazy Redis client helper."""

from functools import lru_cache

import redis

import config


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Return the shared Redis client; connection is established on use."""
    return redis.Redis.from_url(config.REDIS_URL, decode_responses=True)


def clear_redis_cache() -> None:
    """Reset the cached client, useful in tests and configuration reloads."""
    get_redis.cache_clear()
