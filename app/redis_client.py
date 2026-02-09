# app/redis_client.py
import redis.asyncio as redis
from .config import settings
import json
import logging
from typing import Any, Optional, List

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client with connection pooling and automatic reconnection
    """
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.pool: Optional[redis.ConnectionPool] = None
    
    async def connect(self):
        """Initialize Redis connection with connection pooling"""
        try:
            if self.redis:
                logger.warning("⚠️ Redis already connected")
                return
            
            # Create connection pool for better performance
            self.pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=50,  # Connection pool size
                socket_keepalive=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            
            self.redis = redis.Redis(connection_pool=self.pool)
            
            # Test connection
            await self.redis.ping()
            
            logger.info("✅ Redis connected with connection pooling")
            
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            self.redis = None
            self.pool = None
            raise
    
    async def disconnect(self):
        """Close Redis connection and pool"""
        try:
            if self.redis:
                await self.redis.close()
                logger.info("✅ Redis connection closed")
            
            if self.pool:
                await self.pool.disconnect()
                logger.info("✅ Redis pool disconnected")
            
            self.redis = None
            self.pool = None
            
        except Exception as e:
            logger.error(f"❌ Redis disconnect error: {e}")
    
    async def _ensure_connected(self):
        """Ensure Redis is connected (auto-reconnect)"""
        if not self.redis:
            await self.connect()
    
    async def ping(self) -> bool:
        """Check if Redis is alive"""
        try:
            await self._ensure_connected()
            return await self.redis.ping()
        except Exception as e:
            logger.error(f"❌ Redis ping failed: {e}")
            return False
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from Redis with JSON deserialization"""
        try:
            await self._ensure_connected()
            
            value = await self.redis.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
            
        except Exception as e:
            logger.error(f"❌ Redis GET error for key '{key}': {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        expire: Optional[int] = None
    ) -> bool:
        """
        Set value in Redis with JSON serialization
        
        Args:
            key: Redis key
            value: Value to store (will be JSON serialized if not string)
            expire: Expiration time in seconds (default: REDIS_CACHE_EXPIRATION)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            await self._ensure_connected()
            
            if expire is None:
                expire = settings.REDIS_CACHE_EXPIRATION
            
            # Serialize value
            serialized_value = json.dumps(value) if not isinstance(value, str) else value
            
            # Set with expiration
            result = await self.redis.setex(key, expire, serialized_value)
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"❌ Redis SET error for key '{key}': {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from Redis"""
        try:
            await self._ensure_connected()
            result = await self.redis.delete(key)
            return bool(result)
            
        except Exception as e:
            logger.error(f"❌ Redis DELETE error for key '{key}': {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis"""
        try:
            await self._ensure_connected()
            result = await self.redis.exists(key)
            return bool(result)
            
        except Exception as e:
            logger.error(f"❌ Redis EXISTS error for key '{key}': {e}")
            return False
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment a counter"""
        try:
            await self._ensure_connected()
            return await self.redis.incrby(key, amount)
            
        except Exception as e:
            logger.error(f"❌ Redis INCR error for key '{key}': {e}")
            return 0
    
    async def decrement(self, key: str, amount: int = 1) -> int:
        """Decrement a counter"""
        try:
            await self._ensure_connected()
            return await self.redis.decrby(key, amount)
            
        except Exception as e:
            logger.error(f"❌ Redis DECR error for key '{key}': {e}")
            return 0
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on a key"""
        try:
            await self._ensure_connected()
            result = await self.redis.expire(key, seconds)
            return bool(result)
            
        except Exception as e:
            logger.error(f"❌ Redis EXPIRE error for key '{key}': {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Get time to live for a key"""
        try:
            await self._ensure_connected()
            return await self.redis.ttl(key)
            
        except Exception as e:
            logger.error(f"❌ Redis TTL error for key '{key}': {e}")
            return -2
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching pattern"""
        try:
            await self._ensure_connected()
            keys = await self.redis.keys(pattern)
            return [key.decode() if isinstance(key, bytes) else key for key in keys]
            
        except Exception as e:
            logger.error(f"❌ Redis KEYS error for pattern '{pattern}': {e}")
            return []
    
    async def flush_all(self) -> bool:
        """Flush all keys (use with caution!)"""
        try:
            await self._ensure_connected()
            await self.redis.flushall()
            logger.warning("⚠️ Redis FLUSHALL executed - all keys deleted")
            return True
            
        except Exception as e:
            logger.error(f"❌ Redis FLUSHALL error: {e}")
            return False
    
    async def get_info(self) -> dict:
        """Get Redis server info"""
        try:
            await self._ensure_connected()
            info = await self.redis.info()
            return info
            
        except Exception as e:
            logger.error(f"❌ Redis INFO error: {e}")
            return {}
    
    async def get_stats(self) -> dict:
        """Get Redis statistics"""
        try:
            info = await self.get_info()
            
            return {
                "connected": await self.ping(),
                "version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory": info.get("used_memory_human", "0B"),
                "used_memory_peak": info.get("used_memory_peak_human", "0B"),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
                "keyspace": info.get("db0", {}),
            }
            
        except Exception as e:
            logger.error(f"❌ Redis stats error: {e}")
            return {
                "connected": False,
                "error": str(e)
            }


# Global Redis client instance
redis_client = RedisClient()


# Helper function for easy stats access
async def get_redis_stats() -> dict:
    """Get Redis statistics (convenience function)"""
    return await redis_client.get_stats()


# Export
__all__ = ['redis_client', 'get_redis_stats']