from typing import Any, Optional, List
from ..redis_client import redis_client
import json

class CacheService:
    def __init__(self):
        self.redis = redis_client

    async def get_movie(self, movie_id: int) -> Optional[dict]:
        """Get cached movie data"""
        key = f"movie:{movie_id}"
        return await self.redis.get(key)

    async def set_movie(self, movie_id: int, movie_data: dict, expire: int = 3600) -> bool:
        """Cache movie data"""
        key = f"movie:{movie_id}"
        return await self.redis.set(key, movie_data, expire)

    async def get_series(self, series_id: int) -> Optional[dict]:
        """Get cached series data"""
        key = f"series:{series_id}"
        return await self.redis.get(key)

    async def set_series(self, series_id: int, series_data: dict, expire: int = 3600) -> bool:
        """Cache series data"""
        key = f"series:{series_id}"
        return await self.redis.set(key, series_data, expire)

    async def get_featured_content(self) -> Optional[List[dict]]:
        """Get cached featured content"""
        key = "featured:content"
        return await self.redis.get(key)

    async def set_featured_content(self, content: List[dict], expire: int = 1800) -> bool:
        """Cache featured content"""
        key = "featured:content"
        return await self.redis.set(key, content, expire)

    async def get_user_session(self, user_id: int) -> Optional[dict]:
        """Get user session data"""
        key = f"session:user:{user_id}"
        return await self.redis.get(key)

    async def set_user_session(self, user_id: int, session_data: dict, expire: int = 86400) -> bool:
        """Cache user session data"""
        key = f"session:user:{user_id}"
        return await self.redis.set(key, session_data, expire)

    async def invalidate_movie(self, movie_id: int) -> bool:
        """Invalidate movie cache"""
        key = f"movie:{movie_id}"
        return await self.redis.delete(key)

    async def invalidate_series(self, series_id: int) -> bool:
        """Invalidate series cache"""
        key = f"series:{series_id}"
        return await self.redis.delete(key)

    async def invalidate_featured_content(self) -> bool:
        """Invalidate featured content cache"""
        key = "featured:content"
        return await self.redis.delete(key)

    async def increment_view_count(self, content_type: str, content_id: int) -> int:
        """Increment view count for content"""
        key = f"views:{content_type}:{content_id}"
        if not await self.redis.exists(key):
            await self.redis.set(key, 0)
        
        # Use Redis INCR for atomic increment
        if not self.redis.redis:
            await self.redis.connect()
        return await self.redis.redis.incr(key)

cache_service = CacheService()