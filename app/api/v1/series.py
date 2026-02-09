"""
Series Management with HLS Conversion + Redis Caching
- Async database operations
- Redis caching for faster loading
- Concurrent file uploads
- HLS video processing (no trailers - episodes have HLS videos)
- Production-ready
- DELETE endpoint added
"""

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, update, delete
from sqlalchemy.orm import selectinload
import logging
import json
import asyncio
import uuid
import tempfile
import os

from ...database import get_async_db, AsyncSessionLocal
from ...redis_client import redis_client
from ...models import Series, Genre, Category, Episode
from ...services.watch_time_service import watch_time_service
from ...utils.storage import storage_service
from ...services.video_tasks import video_task_service, VideoProcessingStatus
from ..deps import User, get_current_superuser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/series", tags=["series"])

# HLS job tracking
HLS_JOBS_KEY = "hls:processing:jobs"

# ==================== PYDANTIC MODELS ====================

class SeriesCreate(BaseModel):
    title: str
    slug: str
    description: str
    synopsis: Optional[str] = None
    total_seasons: int = 1
    release_year: Optional[int] = None
    rating: float = 0.0
    content_rating: Optional[str] = None
    language: Optional[str] = "English"
    director: Optional[str] = None
    production: Optional[str] = None
    category_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    is_featured: bool = False
    is_active: bool = True
    is_completed: bool = False


class SeriesUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    synopsis: Optional[str] = None
    total_seasons: Optional[int] = None
    release_year: Optional[int] = None
    rating: Optional[float] = None
    content_rating: Optional[str] = None
    language: Optional[str] = None
    director: Optional[str] = None
    production: Optional[str] = None
    category_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_completed: Optional[bool] = None


# ==================== HELPER FUNCTIONS ====================

async def format_series(series: Series, db: AsyncSession) -> dict:
    """Format series with category name and genres (async)"""
    category_name = None
    if series.category_id:
        result = await db.execute(
            select(Category).where(Category.id == series.category_id)
        )
        category = result.scalar_one_or_none()
        category_name = category.name if category else None
    
    # Get genres
    genres = []
    if hasattr(series, 'genres') and series.genres:
        genres = [{"id": g.id, "name": g.name, "slug": g.slug} for g in series.genres]
    
    return {
        "id": series.id,
        "title": series.title,
        "slug": series.slug,
        "description": series.description,
        "synopsis": series.synopsis,
        "poster_url": series.poster_url,
        "banner_url": series.banner_url,
        "trailer_url": series.trailer_url,
        "total_seasons": series.total_seasons,
        "total_episodes": series.total_episodes,
        "release_year": series.release_year,
        "rating": series.rating,
        "view_count": series.view_count,
        "content_rating": series.content_rating,
        "language": series.language,
        "director": series.director,
        "production": series.production,
        "category_id": series.category_id,
        "category_name": category_name,
        "genres": genres,
        "is_active": series.is_active,
        "is_featured": series.is_featured,
        "is_completed": series.is_completed,
        "status": series.status,
        "created_at": series.created_at.isoformat() if series.created_at else None,
        "updated_at": series.updated_at.isoformat() if series.updated_at else None,
    }


async def invalidate_series_cache():
    """Invalidate all series cache entries"""
    try:
        keys = await redis_client.keys("series:*")
        if keys:
            for key in keys:
                await redis_client.delete(key)
            logger.info(f"🗑️ Invalidated {len(keys)} series cache entries")
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")


# ==================== SERIES LIST (ASYNC + REDIS) ====================

@router.get("/list", status_code=status.HTTP_200_OK)
async def list_series(
    skip: int = 0,
    limit: int = 100,
    sort: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_completed: Optional[bool] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """Get all series with pagination, filtering, and Redis caching"""
    try:
        # Create cache key
        cache_key = f"series:list:skip={skip}:limit={limit}:sort={sort}:active={is_active}:completed={is_completed}"
        
        # Try cache first
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.info("✅ Cache hit for series list")
            return cached_data
        
        logger.info(f"📋 Fetching series: skip={skip}, limit={limit}")
        
        # Build query with EAGER LOADING
        query = select(Series).options(
            selectinload(Series.genres),
            selectinload(Series.category)
        )

        # Apply filters
        if is_active is not None:
            query = query.where(Series.is_active == is_active)
        
        if is_completed is not None:
            query = query.where(Series.is_completed == is_completed)

        # Get total count
        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()

        # Apply sorting
        if sort == "title":
            query = query.order_by(Series.title)
        elif sort == "views":
            query = query.order_by(Series.view_count.desc())
        elif sort == "rating":
            query = query.order_by(Series.rating.desc())
        elif sort == "episodes":
            query = query.order_by(Series.total_episodes.desc())
        else:
            query = query.order_by(Series.created_at.desc())

        # Apply pagination
        query = query.offset(skip).limit(limit)
        
        result = await db.execute(query)
        series_list = result.scalars().all()

        # Format series directly (no asyncio.gather)
        formatted_series = []
        for series in series_list:
            formatted_series.append({
                "id": series.id,
                "title": series.title,
                "slug": series.slug,
                "description": series.description,
                "synopsis": series.synopsis,
                "poster_url": series.poster_url,
                "banner_url": series.banner_url,
                "trailer_url": series.trailer_url,
                "total_seasons": series.total_seasons,
                "total_episodes": series.total_episodes,
                "release_year": series.release_year,
                "rating": series.rating,
                "view_count": series.view_count,
                "content_rating": series.content_rating,
                "language": series.language,
                "director": series.director,
                "production": series.production,
                "category_id": series.category_id,
                "category_name": series.category.name if series.category else None,
                "genres": [{"id": g.id, "name": g.name, "slug": g.slug} for g in series.genres],
                "is_active": series.is_active,
                "is_featured": series.is_featured,
                "is_completed": series.is_completed,
                "status": series.status,
                "created_at": series.created_at.isoformat() if series.created_at else None,
                "updated_at": series.updated_at.isoformat() if series.updated_at else None,
            })

        response = {
            "series": formatted_series,
            "total": total,
            "skip": skip,
            "limit": limit,
        }
        
        # Cache for 2 minutes
        await redis_client.set(cache_key, response, expire=120)
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching series: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch series")


# ==================== SERIES STATS (ASYNC + REDIS) ====================

@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_series_stats(db: AsyncSession = Depends(get_async_db)):
    """Get series statistics with Redis caching"""
    try:
        # Try cache first
        cache_key = "series:stats"
        cached_stats = await redis_client.get(cache_key)
        
        if cached_stats:
            logger.info("✅ Cache hit for series stats")
            return cached_stats
        
        # Execute queries SEQUENTIALLY (not concurrently)
        # Single session can't handle concurrent operations
        
        total_result = await db.execute(select(func.count(Series.id)))
        total_series = total_result.scalar() or 0
        
        episodes_result = await db.execute(select(func.sum(Series.total_episodes)))
        total_episodes = int(episodes_result.scalar() or 0)
        
        views_result = await db.execute(select(func.sum(Series.view_count)))
        total_views = int(views_result.scalar() or 0)
        
        rating_result = await db.execute(select(func.avg(Series.rating)))
        avg_rating = round(float(rating_result.scalar() or 0.0), 1)
        
        stats = {
            "total_series": total_series,
            "total_episodes": total_episodes,
            "total_views": total_views,
            "avg_rating": avg_rating
        }
        
        # Cache for 5 minutes
        await redis_client.set(cache_key, stats, expire=300)
        
        return stats
        
    except Exception as e:
        logger.error(f"Error fetching series stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch series stats")


# ==================== GET SINGLE SERIES (ASYNC + REDIS) ===================


# Also fix get_series endpoint
@router.get("/{series_id}")
async def get_series(
    series_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """Get series by ID with all related data"""
    try:
        logger.info(f"📡 Fetching series ID: {series_id}")
        
        # Try cache first
        cache_key = f"series:{series_id}"
        cached_series = await redis_client.get(cache_key)
        
        if cached_series:
            logger.info(f"✅ Cache hit for series {series_id}")
            return cached_series
        
        # Fetch with EAGER LOADING
        result = await db.execute(
            select(Series)
            .options(
                selectinload(Series.genres),
                selectinload(Series.category)
            )
            .where(Series.id == series_id)
        )
        series = result.scalar_one_or_none()
        
        if not series:
            logger.warning(f"❌ Series not found: {series_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Series with ID {series_id} not found"
            )
        
        # Format response
        series_data = {
            "id": series.id,
            "title": series.title,
            "slug": series.slug,
            "description": series.description,
            "synopsis": series.synopsis,
            "poster_url": series.poster_url,
            "banner_url": series.banner_url,
            "trailer_url": series.trailer_url,
            "total_seasons": series.total_seasons,
            "total_episodes": series.total_episodes,
            "release_year": series.release_year,
            "rating": series.rating,
            "view_count": series.view_count,
            "content_rating": series.content_rating,
            "language": series.language,
            "director": series.director,
            "production": series.production,
            "category_id": series.category_id,
            "category_name": series.category.name if series.category else None,
            "genres": [{"id": g.id, "name": g.name, "slug": g.slug} for g in series.genres],
            "is_active": series.is_active,
            "is_featured": series.is_featured,
            "is_completed": series.is_completed,
            "status": series.status,
            "created_at": series.created_at.isoformat() if series.created_at else None,
            "updated_at": series.updated_at.isoformat() if series.updated_at else None,
        }
        
        response = {"data": series_data}
        
        # Cache for 10 minutes
        await redis_client.set(cache_key, response, expire=600)
        
        logger.info(f"✅ Series fetched: {series.title}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching series {series_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch series: {str(e)}"
        )


# ==================== CREATE SERIES (ASYNC + CONCURRENT UPLOADS) ====================

@router.post("/add", status_code=status.HTTP_201_CREATED)
async def create_series(
    title: str = Form(...),
    slug: str = Form(...),
    description: str = Form(...),
    synopsis: Optional[str] = Form(None),
    total_seasons: int = Form(1),
    release_year: Optional[int] = Form(None),
    rating: float = Form(0.0),
    content_rating: Optional[str] = Form(None),
    language: str = Form("English"),
    director: Optional[str] = Form(None),
    production: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    genre_ids: Optional[str] = Form(None),
    is_featured: bool = Form(False),
    is_active: bool = Form(True),
    is_completed: bool = Form(False),
    # File uploads
    poster_file: Optional[UploadFile] = File(None),
    banner_file: Optional[UploadFile] = File(None),
    trailer_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create new series with CONCURRENT file uploads
    
    **Optimizations:**
    - Poster, banner, trailer upload concurrently
    - Redis cache invalidation
    - Async database operations
    """
    try:
        # Check if slug exists
        result = await db.execute(
            select(Series).where(Series.slug == slug)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            raise HTTPException(status_code=400, detail="Series with this slug already exists")
        
        # Parse JSON fields
        genre_ids_list = json.loads(genre_ids) if genre_ids else []
        
        logger.info(f"📺 Creating series: {title}")

        # ═══════════════════════════════════════════════════════════════
        # CONCURRENT FILE UPLOADS
        # ═══════════════════════════════════════════════════════════════
        upload_tasks = []
        
        if trailer_file:
            logger.info(f"📹 Uploading trailer: {trailer_file.filename}")
            upload_tasks.append(
                storage_service.upload_file(
                    trailer_file.file,
                    trailer_file.filename,
                    trailer_file.content_type or 'video/mp4',
                    file_category='trailer'
                )
            )
        else:
            upload_tasks.append(asyncio.sleep(0))
        
        if poster_file:
            logger.info(f"🖼️ Uploading poster: {poster_file.filename}")
            upload_tasks.append(
                storage_service.upload_file(
                    poster_file.file,
                    poster_file.filename,
                    poster_file.content_type or 'image/jpeg',
                    file_category='poster'
                )
            )
        else:
            upload_tasks.append(asyncio.sleep(0))
        
        if banner_file:
            logger.info(f"🖼️ Uploading banner: {banner_file.filename}")
            upload_tasks.append(
                storage_service.upload_file(
                    banner_file.file,
                    banner_file.filename,
                    banner_file.content_type or 'image/jpeg',
                    file_category='banner'
                )
            )
        else:
            upload_tasks.append(asyncio.sleep(0))
        
        # Upload all files concurrently
        results = await asyncio.gather(*upload_tasks, return_exceptions=True)
        
        # Extract URLs
        trailer_url = None if isinstance(results[0], Exception) or results[0] == None else results[0][1]
        poster_url = None if isinstance(results[1], Exception) or results[1] == None else results[1][1]
        banner_url = None if isinstance(results[2], Exception) or results[2] == None else results[2][1]
        
        logger.info("✅ All files uploaded concurrently")

        # ═══════════════════════════════════════════════════════════════
        # CREATE SERIES IN DATABASE
        # ═══════════════════════════════════════════════════════════════
        series = Series(
            title=title,
            slug=slug,
            description=description,
            poster_url=poster_url,
            banner_url=banner_url,
            trailer_url=trailer_url,
            synopsis=synopsis or (description[:500] if len(description) > 500 else description),
            total_seasons=total_seasons,
            release_year=release_year,
            rating=rating,
            content_rating=content_rating,
            language=language,
            director=director,
            production=production,
            category_id=category_id,
            is_featured=is_featured,
            is_active=is_active,
            is_completed=is_completed,
        )
        
        # Add genres if provided
        if genre_ids_list:
            for genre_id in genre_ids_list:
                result = await db.execute(
                    select(Genre).where(Genre.id == genre_id)
                )
                genre = result.scalar_one_or_none()
                if genre:
                    series.genres.append(genre)
        
        db.add(series)
        await db.commit()
        await db.refresh(series)
        
        # Invalidate cache
        await invalidate_series_cache()
        
        logger.info(f"✅ Series created: {series.title} (ID: {series.id})")
        
        return {
            "data": {
                "id": series.id,
                "title": series.title,
                "slug": series.slug,
                "poster_url": poster_url,
                "banner_url": banner_url,
                "trailer_url": trailer_url,
                "message": "Series created successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error creating series: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create series: {str(e)}")


# ==================== UPDATE SERIES (ASYNC + REDIS INVALIDATION) ====================

@router.put("/{series_id}")
async def update_series(
    series_id: int,
    title: Optional[str] = Form(None),
    slug: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    synopsis: Optional[str] = Form(None),
    total_seasons: Optional[int] = Form(None),
    release_year: Optional[int] = Form(None),
    rating: Optional[float] = Form(None),
    content_rating: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    production: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    genre_ids: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    is_featured: Optional[bool] = Form(None),
    is_completed: Optional[bool] = Form(None),
    # Optional file uploads
    poster_file: Optional[UploadFile] = File(None),
    banner_file: Optional[UploadFile] = File(None),
    trailer_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_async_db)
):
    """Update series with optional file replacements"""
    try:
        # ═══════════════════════════════════════════════════════════
        # FIX: Load series with EAGER LOADING to avoid lazy load issues
        # ═══════════════════════════════════════════════════════════
        result = await db.execute(
            select(Series)
            .options(selectinload(Series.genres))  # <-- EAGER LOAD genres
            .where(Series.id == series_id)
        )
        series = result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
        
        # Check slug conflict
        if slug and slug != series.slug:
            existing_result = await db.execute(
                select(Series).where(
                    and_(
                        Series.slug == slug,
                        Series.id != series_id
                    )
                )
            )
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                raise HTTPException(status_code=400, detail="Series with this slug already exists")
        
        # Update text fields
        if title is not None:
            series.title = title
        if slug is not None:
            series.slug = slug
        if description is not None:
            series.description = description
        if synopsis is not None:
            series.synopsis = synopsis
        if total_seasons is not None:
            series.total_seasons = total_seasons
        if release_year is not None:
            series.release_year = release_year
        if rating is not None:
            series.rating = rating
        if content_rating is not None:
            series.content_rating = content_rating
        if language is not None:
            series.language = language
        if director is not None:
            series.director = director
        if production is not None:
            series.production = production
        if category_id is not None:
            series.category_id = category_id
        if is_active is not None:
            series.is_active = is_active
        if is_featured is not None:
            series.is_featured = is_featured
        if is_completed is not None:
            series.is_completed = is_completed
        
        # ═══════════════════════════════════════════════════════════
        # FIX: Update genres - Clear and reload properly
        # ═══════════════════════════════════════════════════════════
        if genre_ids is not None:
            genre_ids_list = json.loads(genre_ids)
            
            # Clear existing genres (this is now safe because we eager loaded)
            series.genres.clear()
            
            # Add new genres
            for genre_id in genre_ids_list:
                genre_result = await db.execute(
                    select(Genre).where(Genre.id == genre_id)
                )
                genre = genre_result.scalar_one_or_none()
                if genre:
                    series.genres.append(genre)
        
        # Handle file uploads concurrently
        upload_tasks = []
        
        if trailer_file:
            async def update_trailer():
                if series.trailer_url:
                    await storage_service.delete_file(series.trailer_url, 'r2')
                _, url = await storage_service.upload_file(
                    trailer_file.file,
                    trailer_file.filename,
                    trailer_file.content_type or 'video/mp4',
                    file_category='trailer'
                )
                return url
            
            upload_tasks.append(update_trailer())
        else:
            upload_tasks.append(asyncio.sleep(0))
        
        if poster_file:
            async def update_poster():
                if series.poster_url:
                    await storage_service.delete_file(series.poster_url, 'firebase')
                _, url = await storage_service.upload_file(
                    poster_file.file,
                    poster_file.filename,
                    poster_file.content_type or 'image/jpeg',
                    file_category='poster'
                )
                return url
            
            upload_tasks.append(update_poster())
        else:
            upload_tasks.append(asyncio.sleep(0))
        
        if banner_file:
            async def update_banner():
                if series.banner_url:
                    await storage_service.delete_file(series.banner_url, 'firebase')
                _, url = await storage_service.upload_file(
                    banner_file.file,
                    banner_file.filename,
                    banner_file.content_type or 'image/jpeg',
                    file_category='banner'
                )
                return url
            
            upload_tasks.append(update_banner())
        else:
            upload_tasks.append(asyncio.sleep(0))
        
        # Execute uploads concurrently
        results = await asyncio.gather(*upload_tasks, return_exceptions=True)
        
        # Update URLs if uploads succeeded
        if trailer_file and not isinstance(results[0], Exception):
            series.trailer_url = results[0]
        if poster_file and not isinstance(results[1], Exception):
            series.poster_url = results[1]
        if banner_file and not isinstance(results[2], Exception):
            series.banner_url = results[2]
        
        # ═══════════════════════════════════════════════════════════
        # FIX: Auto-update total_episodes and total_seasons from database
        # ═══════════════════════════════════════════════════════════
        # Count actual episodes
        episode_count_result = await db.execute(
            select(func.count(Episode.id)).where(Episode.series_id == series_id)
        )
        actual_episode_count = episode_count_result.scalar() or 0
        
        # Get distinct seasons
        seasons_result = await db.execute(
            select(func.count(func.distinct(Episode.season_number)))
            .where(Episode.series_id == series_id)
        )
        actual_season_count = seasons_result.scalar() or 0
        
        # Update series with actual counts
        series.total_episodes = actual_episode_count
        if total_seasons is None:  # Only auto-update if not manually set in this request
            series.total_seasons = max(actual_season_count, 1)  # At least 1 season
        
        await db.commit()
        await db.refresh(series)
        
        # Invalidate cache
        await redis_client.delete(f"series:{series_id}")
        await invalidate_series_cache()
        
        logger.info(f"✅ Series updated: {series.title} ({actual_episode_count} episodes, {series.total_seasons} seasons)")
        
        return {
            "data": {
                "id": series.id,
                "title": series.title,
                "total_episodes": series.total_episodes,
                "total_seasons": series.total_seasons,
                "message": "Series updated successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error updating series {series_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update series: {str(e)}")


# ==================== DELETE SERIES (ASYNC + CASCADE) ====================

@router.delete("/{series_id}", status_code=status.HTTP_200_OK)
async def delete_series(
    series_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Delete series and all associated data (episodes, etc.)
    
    **Cascading Deletion:**
    - Deletes all episodes for this series
    - Deletes poster, banner, trailer from storage
    - Deletes all episode videos from storage
    - Invalidates all caches
    """
    try:
        logger.info(f"🗑️ Deleting series ID: {series_id}")
        
        # Fetch series with genres
        result = await db.execute(
            select(Series)
            .options(selectinload(Series.genres))
            .where(Series.id == series_id)
        )
        series = result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Series with ID {series_id} not found"
            )
        
        # Get all episodes for this series
        episodes_result = await db.execute(
            select(Episode).where(Episode.series_id == series_id)
        )
        episodes = episodes_result.scalars().all()
        
        # Delete all episode videos and thumbnails from storage
        deletion_tasks = []
        
        for episode in episodes:
            # Delete episode video file (HLS video)
            if episode.video_url:
                deletion_tasks.append(
                    storage_service.delete_file(episode.video_url, 'r2')
                )
            
            # Delete episode thumbnail
            if episode.thumbnail_url:
                deletion_tasks.append(
                    storage_service.delete_file(episode.thumbnail_url, 'firebase')
                )
        
        # Delete series media files
        if series.poster_url:
            deletion_tasks.append(
                storage_service.delete_file(series.poster_url, 'firebase')
            )
        
        if series.banner_url:
            deletion_tasks.append(
                storage_service.delete_file(series.banner_url, 'firebase')
            )
        
        if series.trailer_url:
            deletion_tasks.append(
                storage_service.delete_file(series.trailer_url, 'r2')
            )
        
        # Execute all file deletions concurrently
        if deletion_tasks:
            logger.info(f"📦 Deleting {len(deletion_tasks)} files from storage...")
            await asyncio.gather(*deletion_tasks, return_exceptions=True)
            logger.info("✅ Storage files deleted")
        
        # Delete all episodes from database
        if episodes:
            await db.execute(
                delete(Episode).where(Episode.series_id == series_id)
            )
            logger.info(f"✅ Deleted {len(episodes)} episodes")
        
        # Delete the series (genres are automatically unlinked)
        await db.delete(series)
        await db.commit()
        
        # Invalidate all caches
        await redis_client.delete(f"series:{series_id}")
        await invalidate_series_cache()
        
        logger.info(f"✅ Series deleted: {series.title} (ID: {series_id})")
        
        return {
            "success": True,
            "data": {
                "series_id": series_id,
                "series_title": series.title,
                "episodes_deleted": len(episodes),
                "message": f"Series '{series.title}' and all {len(episodes)} episodes deleted successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error deleting series {series_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete series: {str(e)}"
        )


# ==================== HELPER FUNCTION TO SYNC EPISODE COUNTS ====================

async def sync_series_episode_counts(db: AsyncSession, series_id: int):
    """
    Sync series episode and season counts from Episode table
    Call this after creating/deleting episodes
    """
    try:
        # Count episodes
        episode_count_result = await db.execute(
            select(func.count(Episode.id)).where(Episode.series_id == series_id)
        )
        total_episodes = episode_count_result.scalar() or 0
        
        # Count distinct seasons
        seasons_result = await db.execute(
            select(func.count(func.distinct(Episode.season_number)))
            .where(Episode.series_id == series_id)
        )
        total_seasons = seasons_result.scalar() or 0
        
        # Update series
        await db.execute(
            update(Series)
            .where(Series.id == series_id)
            .values(
                total_episodes=total_episodes,
                total_seasons=max(total_seasons, 1)  # At least 1 season
            )
        )
        
        logger.info(f"✅ Synced series {series_id}: {total_episodes} episodes, {total_seasons} seasons")
        
        return {"total_episodes": total_episodes, "total_seasons": total_seasons}
        
    except Exception as e:
        logger.error(f"❌ Error syncing series counts: {e}")
        raise


# ==================== SYNC ENDPOINTS FOR MANUAL FIX ====================

@router.post("/{series_id}/sync-counts")
async def sync_series_counts(
    series_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Manually sync episode/season counts for a series
    Useful for fixing mismatched data
    """
    try:
        # Verify series exists
        result = await db.execute(
            select(Series).where(Series.id == series_id)
        )
        series = result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
        
        # Sync counts
        counts = await sync_series_episode_counts(db, series_id)
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete(f"series:{series_id}")
        await invalidate_series_cache()
        
        return {
            "data": {
                "series_id": series_id,
                "series_title": series.title,
                "synced_counts": counts,
                "message": "Counts synchronized successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error syncing counts: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync counts")


@router.post("/sync-all-counts")
async def sync_all_series_counts(db: AsyncSession = Depends(get_async_db)):
    """
    Sync episode/season counts for ALL series
    Run this once to fix existing data
    """
    try:
        # Get all series
        result = await db.execute(select(Series))
        all_series = result.scalars().all()
        
        synced_count = 0
        results = []
        
        for series in all_series:
            try:
                counts = await sync_series_episode_counts(db, series.id)
                results.append({
                    "series_id": series.id,
                    "title": series.title,
                    "before": {
                        "total_episodes": series.total_episodes,
                        "total_seasons": series.total_seasons
                    },
                    "after": counts
                })
                synced_count += 1
            except Exception as e:
                logger.error(f"Failed to sync series {series.id}: {e}")
                results.append({
                    "series_id": series.id,
                    "title": series.title,
                    "error": str(e)
                })
        
        await db.commit()
        
        # Invalidate all cache
        await invalidate_series_cache()
        
        logger.info(f"✅ Synced {synced_count}/{len(all_series)} series")
        
        return {
            "data": {
                "total_series": len(all_series),
                "synced": synced_count,
                "results": results,
                "message": f"Synchronized {synced_count} series successfully"
            }
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error syncing all series: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync all series")


# ==================== TRACK VIEW (ASYNC + REDIS) ====================

@router.post("/{series_id}/track-view", status_code=status.HTTP_200_OK)
async def track_series_view(series_id: int, db: AsyncSession = Depends(get_async_db)):
    """Track series view - increment view count"""
    try:
        # Increment in Redis
        redis_key = f"series:{series_id}:views"
        await redis_client.increment(redis_key)
        
        # Update database
        await db.execute(
            update(Series)
            .where(Series.id == series_id)
            .values(view_count=Series.view_count + 1)
        )
        await db.commit()
        
        # Get updated count
        result = await db.execute(
            select(Series.view_count, Series.title).where(Series.id == series_id)
        )
        row = result.one_or_none()
        
        if not row:
            raise HTTPException(status_code=404, detail="Series not found")
        
        view_count, title = row
        
        # Invalidate cache
        await redis_client.delete(f"series:{series_id}")
        
        logger.info(f"✅ View tracked for series: {title} (Total: {view_count})")
        
        return {
            "data": {
                "series_id": series_id,
                "title": title,
                "view_count": view_count,
                "message": "View tracked successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error tracking view: {e}")
        raise HTTPException(status_code=500, detail="Failed to track view")
    

@router.get("/{series_id}/analytics", status_code=status.HTTP_200_OK)
async def get_series_analytics(
    series_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    📈 Get comprehensive series analytics (ADMIN ONLY)
    
    **Returns:**
    - Series-level views and watch-time
    - Episode-by-episode breakdown
    - Binge-watching metrics
    - Drop-off analysis
    - Payment information
    
    **Example Response:**
    ```json
    {
        "views": {
            "total_views": 1000,
            "rewatched_views": 200
        },
        "watch_time": {
            "effective_watch_time_minutes": 165000.0
        },
        "engagement": {
            "average_episodes_per_viewer": 7.5,
            "binge_rate": 35.2,
            "drop_off_episode": 5
        },
        "payment": {
            "monthly_earnings_tzs": 495000.0
        },
        "episodes_breakdown": [...]
    }
    ```
    """
    try:
        analytics_data = await watch_time_service.get_series_analytics(
            db=db,
            series_id=series_id
        )
        
        return {
            "success": True,
            "data": analytics_data
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting series analytics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")