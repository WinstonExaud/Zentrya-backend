"""
Movie Upload with Direct HLS Conversion + Redis Caching + Watch-Time Tracking
- Async database operations
- Redis caching for faster loading
- Concurrent file uploads
- Non-blocking HLS processing with proper async handling
- Netflix-grade watch-time tracking
- Producer payment analytics

FIX: Proper background task handling to avoid greenlet_spawn errors
"""

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, update, delete, desc, asc
from sqlalchemy.orm import selectinload
import logging
import json
import tempfile
import os
import uuid
import asyncio

from ...database import get_async_db, AsyncSessionLocal
from ...redis_client import redis_client
from ...models import Movie, Genre, Category, User
from ...utils.storage import storage_service
from ...services.video_tasks import video_task_service, VideoProcessingStatus
from ...services.watch_time_service import watch_time_service
from ...models.watch_analytics import WatchSession as WatchSessionModel, MovieAnalytics
from ..deps import get_current_superuser, get_current_user

logger = logging.getLogger(__name__) 
router = APIRouter(prefix="/movies", tags=["movies"])

# Job status tracker (stored in Redis in production)
HLS_JOBS_KEY = "hls:processing:jobs"

# ==================== PYDANTIC MODELS ====================

class MovieCreate(BaseModel):
    title: str
    slug: str
    description: str
    synopsis: Optional[str] = None
    duration: Optional[int] = None
    release_year: Optional[int] = None
    rating: float = 0
    content_rating: Optional[str] = None
    language: str = "English"
    director: Optional[str] = None
    production: Optional[str] = None
    cast: Optional[List[str]] = None
    category_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    is_featured: bool = False
    is_active: bool = False


class MovieUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    synopsis: Optional[str] = None
    duration: Optional[int] = None
    release_year: Optional[int] = None
    rating: Optional[float] = None
    content_rating: Optional[str] = None
    language: Optional[str] = None
    director: Optional[str] = None
    production: Optional[str] = None
    category_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    cast: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None


class WatchStartRequest(BaseModel):
    device_id: Optional[str] = None


class WatchProgressRequest(BaseModel):
    session_id: str
    current_position_seconds: int
    quality_level: Optional[str] = None


class WatchEndRequest(BaseModel):
    session_id: str


async def format_movie(movie: Movie, db: AsyncSession) -> dict:
    """Helper function to format movie with category name (async)"""
    category_name = None
    if movie.category_id:
        result = await db.execute(
            select(Category).where(Category.id == movie.category_id)
        )
        category = result.scalar_one_or_none()
        category_name = category.name if category else None

    return {
        "id": movie.id,
        "title": movie.title,
        "slug": movie.slug,
        "description": movie.description,
        "synopsis": movie.synopsis,
        "poster_url": movie.poster_url,
        "banner_url": movie.banner_url,
        "trailer_url": movie.trailer_url,
        "video_url": movie.video_url,
        "duration": movie.duration,
        "release_year": movie.release_year,
        "rating": movie.rating,
        "content_rating": movie.content_rating,
        "language": movie.language,
        "director": movie.director,
        "production": movie.production,
        "cast": movie.cast,
        "view_count": movie.view_count,
        "category_id": movie.category_id,
        "category_name": category_name,
        "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
        "is_active": movie.is_active,
        "is_featured": movie.is_featured,
        "created_at": movie.created_at.isoformat() if movie.created_at else None,
        "updated_at": movie.updated_at.isoformat() if movie.updated_at else None,
    }


# ==================== MOVIE LIST (ASYNC + REDIS) ====================

@router.get("/list")
async def list_movies(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    sort: Optional[str] = Query(default=None, regex="^(title|created_at|view_count|rating)$"),
    is_active: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_async_db),
):
    """
    📋 List all movies with pagination, filtering, and sorting
    Public endpoint - no auth required
    """
    try:
        logger.info(f"📋 Fetching movies: skip={skip}, limit={limit}, sort={sort}, is_active={is_active}")

        # Build query with EAGER LOADING
        query = select(Movie).options(
            selectinload(Movie.genres),
            selectinload(Movie.category)
        )

        # Apply filters
        if is_active is not None:
            query = query.where(Movie.is_active == is_active)

        # Apply sorting
        if sort:
            if sort == "title":
                query = query.order_by(asc(Movie.title))
            elif sort == "created_at":
                query = query.order_by(desc(Movie.created_at))
            elif sort == "view_count":
                query = query.order_by(desc(Movie.view_count))
            elif sort == "rating":
                query = query.order_by(desc(Movie.rating))
        else:
            query = query.order_by(desc(Movie.created_at))

        # Get total count
        count_query = select(func.count(Movie.id))
        if is_active is not None:
            count_query = count_query.where(Movie.is_active == is_active)
        
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination
        query = query.offset(skip).limit(limit)

        # Execute query
        result = await db.execute(query)
        movies = result.scalars().all()

        logger.info(f"✅ Found {len(movies)} movies (total: {total})")

        # Format movies directly (no asyncio.gather)
        formatted_movies = []
        for movie in movies:
            formatted_movies.append({
                "id": movie.id,
                "title": movie.title,
                "slug": movie.slug,
                "description": movie.description,
                "synopsis": movie.synopsis,
                "poster_url": movie.poster_url,
                "banner_url": movie.banner_url,
                "trailer_url": movie.trailer_url,
                "video_url": movie.video_url,
                "duration": movie.duration,
                "release_year": movie.release_year,
                "rating": movie.rating,
                "view_count": movie.view_count,
                "content_rating": movie.content_rating,
                "language": movie.language,
                "director": movie.director,
                "production": movie.production,
                "category_id": movie.category_id,
                "category_name": movie.category.name if movie.category else None,
                "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
                "cast": movie.cast or [],
                "is_active": movie.is_active,
                "is_featured": movie.is_featured,
                "created_at": movie.created_at.isoformat() if movie.created_at else None,
                "updated_at": movie.updated_at.isoformat() if movie.updated_at else None,
            })

        return {
            "movies": formatted_movies,
            "total": total,
            "skip": skip,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"Error fetching movies: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch movies")



# ==================== GET SINGLE MOVIE (ASYNC + REDIS) ====================

@router.get("/{movie_id}")
async def get_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get single movie by ID with all related data
    """
    try:
        logger.info(f"📡 Fetching movie ID: {movie_id}")
        
        # Try cache first
        cache_key = f"movie:{movie_id}"
        cached_movie = await redis_client.get(cache_key)
        
        if cached_movie:
            logger.info(f"✅ Cache hit for movie {movie_id}")
            return cached_movie
        
        # Fetch movie with EAGER LOADING for relationships
        result = await db.execute(
            select(Movie)
            .options(
                selectinload(Movie.genres),
                selectinload(Movie.category)
            )
            .where(Movie.id == movie_id)
        )
        movie = result.scalar_one_or_none()
        
        if not movie:
            logger.warning(f"❌ Movie not found: {movie_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Movie with ID {movie_id} not found"
            )
        
        # Format response with pre-loaded relationships
        movie_data = {
            "id": movie.id,
            "title": movie.title,
            "slug": movie.slug,
            "description": movie.description,
            "synopsis": movie.synopsis,
            "poster_url": movie.poster_url,
            "banner_url": movie.banner_url,
            "trailer_url": movie.trailer_url,
            "video_url": movie.video_url,
            "duration": movie.duration,
            "release_year": movie.release_year,
            "rating": movie.rating,
            "view_count": movie.view_count,
            "content_rating": movie.content_rating,
            "language": movie.language,
            "director": movie.director,
            "production": movie.production,
            "category_id": movie.category_id,
            "category_name": movie.category.name if movie.category else None,
            "genres": [{"id": g.id, "name": g.name, "slug": g.slug} for g in movie.genres],
            "cast": movie.cast,
            "is_active": movie.is_active,
            "is_featured": movie.is_featured,
            "created_at": movie.created_at.isoformat() if movie.created_at else None,
            "updated_at": movie.updated_at.isoformat() if movie.updated_at else None,
        }
        
        response = {"data": movie_data}
        
        # Cache for 10 minutes
        await redis_client.set(cache_key, response, expire=600)
        
        logger.info(f"✅ Movie fetched: {movie.title}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching movie {movie_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch movie: {str(e)}"
        )


# ==================== TRACK VIEW (LEGACY - KEPT FOR COMPATIBILITY) ====================

@router.post("/{movie_id}/track-view", status_code=status.HTTP_200_OK)
async def track_movie_view(movie_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    LEGACY: Track movie view - increment view count
    ⚠️ This endpoint is deprecated. Use /movies/{movie_id}/watch/start instead
    
    Kept for backward compatibility with old clients
    """
    try:
        # Increment in Redis for fast response
        redis_key = f"movie:{movie_id}:views"
        await redis_client.increment(redis_key)
        
        # Update database (async)
        await db.execute(
            update(Movie)
            .where(Movie.id == movie_id)
            .values(view_count=Movie.view_count + 1)
        )
        await db.commit()
        
        # Get updated count
        result = await db.execute(
            select(Movie.view_count, Movie.title).where(Movie.id == movie_id)
        )
        row = result.one_or_none()
        
        if not row:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        view_count, title = row
        
        # Invalidate cache
        cache_key = f"movie:{movie_id}"
        await redis_client.delete(cache_key)
        
        logger.info(f"✅ View tracked for movie: {title} (Total views: {view_count})")
        
        return {
            "data": {
                "movie_id": movie_id,
                "title": title,
                "view_count": view_count,
                "message": "View tracked successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error tracking view for movie {movie_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to track view")


# ==================== WATCH-TIME TRACKING (NEW SYSTEM) ====================

@router.post("/{movie_id}/watch/start", status_code=status.HTTP_200_OK)
async def start_watch_session(
    movie_id: int,
    request: WatchStartRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    🎬 Start a new watch session
    """
    try:
        # Get movie with duration
        result = await db.execute(
            select(Movie).where(Movie.id == movie_id)
        )
        movie = result.scalar_one_or_none()
        
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        if not movie.duration:
            raise HTTPException(
                status_code=400,
                detail="Movie duration not set. Cannot track watch-time."
            )
        
        # Start session
        session_data = await watch_time_service.start_watch_session(
            db=db,
            user_id=current_user.id,
            movie_id=movie_id,
            video_duration=movie.duration,
            device_id=request.device_id
        )
        
        return {
            "success": True,
            "data": {
                **session_data,
                "movie_title": movie.title,
                "video_duration_seconds": movie.duration,
                "message": "Watch session started successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error starting watch session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start watch session: {str(e)}")


@router.post("/{movie_id}/watch/progress", status_code=status.HTTP_200_OK)
async def update_watch_progress(
    movie_id: int,
    request: WatchProgressRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    📊 Update watch progress during playback
    """
    try:
        progress_data = await watch_time_service.update_watch_progress(
            db=db,
            session_id=request.session_id,
            current_position_seconds=request.current_position_seconds,
            quality_level=request.quality_level
        )
        
        return {
            "success": True,
            "data": progress_data
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error updating watch progress: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update progress: {str(e)}")


@router.post("/{movie_id}/watch/end", status_code=status.HTTP_200_OK)
async def end_watch_session(
    movie_id: int,
    request: WatchEndRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    ⏹️ End watch session and calculate contribution
    """
    try:
        session_data = await watch_time_service.end_watch_session(
            db=db,
            session_id=request.session_id
        )
        
        return {
            "success": True,
            "data": {
                **session_data,
                "message": "Watch session ended successfully"
            }
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error ending watch session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to end session: {str(e)}")


@router.get("/{movie_id}/analytics", status_code=status.HTTP_200_OK)
async def get_movie_analytics(
    movie_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    📈 Get comprehensive movie analytics
    """
    try:
        analytics_data = await watch_time_service.get_movie_analytics(
            db=db,
            movie_id=movie_id
        )
        
        return {
            "success": True,
            "data": analytics_data
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting movie analytics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")


# ==================== CREATE MOVIE WITH HLS (ASYNC + CONCURRENT UPLOADS) ====================

@router.post("/create-with-hls", status_code=status.HTTP_201_CREATED)
async def create_movie_with_hls(
    # Metadata
    title: str = Form(...),
    slug: str = Form(...),
    description: str = Form(...),
    synopsis: Optional[str] = Form(None),
    duration: Optional[int] = Form(None),
    release_year: Optional[int] = Form(None),
    rating: float = Form(0),
    content_rating: Optional[str] = Form(None),
    language: str = Form("English"),
    director: Optional[str] = Form(None),
    production: Optional[str] = Form(None),
    cast: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    genre_ids: Optional[str] = Form(None),
    is_featured: bool = Form(False),
    is_active: bool = Form(False),
    # File uploads
    video_file: UploadFile = File(...),
    trailer_file: Optional[UploadFile] = File(None),
    poster_file: Optional[UploadFile] = File(None),
    banner_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_async_db),
    current_user = Depends(get_current_superuser)
):
    """Create new movie with CONCURRENT file uploads and HLS conversion"""
    try:
        # Check if slug exists
        result = await db.execute(
            select(Movie).where(Movie.slug == slug)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            raise HTTPException(status_code=400, detail="Movie slug already exists")

        # Validate video file
        if not video_file.content_type.startswith('video/'):
            raise HTTPException(status_code=400, detail="Video file must be a video format")

        # Parse JSON fields
        cast_list = json.loads(cast) if cast else []
        genre_ids_list = json.loads(genre_ids) if genre_ids else []

        logger.info(f"🎬 Creating movie: {title}")

        # ═══════════════════════════════════════════════════════════════
        # CONCURRENT FILE UPLOADS (Poster, Banner, Trailer)
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
            upload_tasks.append(asyncio.sleep(0))  # Placeholder
        
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
        
        logger.info(f"✅ All files uploaded concurrently")

        # ═══════════════════════════════════════════════════════════════
        # CREATE MOVIE IN DATABASE (FIXED)
        # ═══════════════════════════════════════════════════════════════
        
        # ✅ Load genres BEFORE creating movie
        genres = []
        if genre_ids_list:
            genre_result = await db.execute(
                select(Genre).where(Genre.id.in_(genre_ids_list))
            )
            genres = genre_result.scalars().all()
            logger.info(f"📚 Loaded {len(genres)} genres")
        
        # Create movie object
        movie = Movie(
            title=title,
            slug=slug,
            description=description,
            synopsis=synopsis,
            duration=duration,
            release_year=release_year,
            rating=rating,
            content_rating=content_rating,
            language=language,
            director=director,
            production=production,
            cast=cast_list,
            category_id=category_id,
            is_featured=is_featured,
            is_active=False,  # Not active until video is ready
            poster_url=poster_url,
            banner_url=banner_url,
            trailer_url=trailer_url,
            video_url=None  # Will be set after HLS processing
        )
        
        # ✅ Assign genres BEFORE adding to session
        if genres:
            movie.genres = list(genres)

        db.add(movie)
        await db.commit()
        await db.refresh(movie)

        logger.info(f"✅ Movie created with ID: {movie.id}")

        # ═══════════════════════════════════════════════════════════════
        # SAVE VIDEO TO TEMP FILE FOR HLS PROCESSING
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"💾 Saving video to temporary file for HLS conversion...")

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        temp_video_path = temp_file.name

        try:
            # Write uploaded video to temp file
            chunk_size = 8192
            while True:
                chunk = await video_file.read(chunk_size)
                if not chunk:
                    break
                temp_file.write(chunk)

            temp_file.close()

            # Generate job ID
            job_id = str(uuid.uuid4())

            # Store job status in Redis
            job_status = {
                'status': VideoProcessingStatus.PENDING,
                'progress': 0,
                'message': 'Queued for HLS conversion',
                'movie_id': movie.id,
                'movie_title': movie.title
            }
            
            await redis_client.set(
                f"{HLS_JOBS_KEY}:{job_id}",
                job_status,
                expire=86400  # 24 hours
            )

            # Start HLS processing in background
            logger.info(f"🎬 Starting background HLS processing for movie {movie.id}")

            asyncio.create_task(
                process_movie_to_hls_background(
                    job_id,
                    movie.id,
                    temp_video_path
                )
            )

            logger.info(f"✅ Movie created successfully! HLS processing queued with job_id: {job_id}")

            return {
                "success": True,
                "message": "Movie created successfully. Video is being converted to HLS format.",
                "movie": {
                    "id": movie.id,
                    "title": movie.title,
                    "slug": movie.slug,
                    "poster_url": movie.poster_url,
                    "banner_url": movie.banner_url,
                    "trailer_url": movie.trailer_url,
                    "is_active": movie.is_active,
                    "video_status": "processing"
                },
                "hls_job": {
                    "job_id": job_id,
                    "status_endpoint": f"/api/v1/movies/hls-status/{job_id}",
                    "estimated_time": "5-15 minutes depending on video length"
                }
            }

        except Exception as e:
            # Cleanup temp file on error
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)

            # Delete created movie
            await db.delete(movie)
            await db.commit()

            raise HTTPException(
                status_code=500,
                detail=f"Failed to process video: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error creating movie: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to create movie: {str(e)}")


# ==================== HLS STATUS (REDIS) ====================

@router.get("/hls-status/{job_id}", status_code=status.HTTP_200_OK)
async def get_hls_processing_status(job_id: str):
    """
    Get HLS processing status from Redis
    """
    job_status = await redis_client.get(f"{HLS_JOBS_KEY}:{job_id}")
    
    if not job_status:
        raise HTTPException(status_code=404, detail="HLS processing job not found")

    return job_status


# ==================== UPDATE MOVIE (ASYNC + REDIS INVALIDATION) ====================

@router.put("/{movie_id}", status_code=status.HTTP_200_OK)
async def update_movie(
    movie_id: int,
    movie_update: MovieUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user = Depends(get_current_superuser)
):
    """Update movie metadata (invalidates cache)"""
    try:
        result = await db.execute(
            select(Movie).where(Movie.id == movie_id)
        )
        movie = result.scalar_one_or_none()
        
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")

        # Update fields
        update_data = movie_update.dict(exclude_unset=True)

        for field, value in update_data.items():
            if field != 'genre_ids':
                setattr(movie, field, value)

        # Update genres if provided
        if 'genre_ids' in update_data:
            movie.genres = []
            for genre_id in update_data['genre_ids']:
                result = await db.execute(
                    select(Genre).where(Genre.id == genre_id)
                )
                genre = result.scalar_one_or_none()
                if genre:
                    movie.genres.append(genre)

        await db.commit()
        await db.refresh(movie)
        
        # Invalidate cache
        await redis_client.delete(f"movie:{movie_id}")
        await invalidate_movies_list_cache()

        return {
            "success": True,
            "message": "Movie updated successfully",
            "movie": await format_movie(movie, db)
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error updating movie: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update movie: {str(e)}")


# ==================== DELETE MOVIE (ASYNC) ====================

@router.delete("/{movie_id}", status_code=status.HTTP_200_OK)
async def delete_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user = Depends(get_current_superuser)
):
    """Delete movie and its HLS files"""
    try:
        result = await db.execute(
            select(Movie).where(Movie.id == movie_id)
        )
        movie = result.scalar_one_or_none()
        
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")

        # Delete HLS files from R2 if exists
        if movie.video_url and 'hls/movies' in movie.video_url:
            logger.info(f"🗑️ Deleting HLS files for movie {movie_id}")
            await video_task_service.delete_hls_video(movie_id, 'movie')

        # Delete from database
        await db.delete(movie)
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete(f"movie:{movie_id}")
        await invalidate_movies_list_cache()

        logger.info(f"✅ Movie {movie_id} deleted successfully")

        return {
            "success": True,
            "message": "Movie deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error deleting movie: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete movie: {str(e)}")

# ==================== UPDATE MOVIE WITH FILES ====================

@router.put("/{movie_id}/update-with-files", status_code=status.HTTP_200_OK)
async def update_movie_with_files(
    movie_id: int,
    # Metadata (all optional)
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    synopsis: Optional[str] = Form(None),
    duration: Optional[int] = Form(None),
    release_year: Optional[int] = Form(None),
    rating: Optional[float] = Form(None),
    content_rating: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    production: Optional[str] = Form(None),
    cast: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    genre_ids: Optional[str] = Form(None),
    is_featured: Optional[bool] = Form(None),
    is_active: Optional[bool] = Form(None),
    # File uploads (all optional)
    video_file: Optional[UploadFile] = File(None),
    trailer_file: Optional[UploadFile] = File(None),
    poster_file: Optional[UploadFile] = File(None),
    banner_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_async_db),
    current_user = Depends(get_current_superuser)
):
    """
    Update movie with optional file replacements
    
    - Only uploads files that are provided
    - Deletes old files from R2 when replacing
    - Updates metadata fields that are provided
    - Keeps existing values for fields not provided
    """
    try:
        logger.info(f"✏️ Updating movie {movie_id}")
        
        # Fetch existing movie
        result = await db.execute(
            select(Movie).options(selectinload(Movie.genres)).where(Movie.id == movie_id)
        )
        movie = result.scalar_one_or_none()
        
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")

        # Store old file URLs for cleanup
        old_poster_url = movie.poster_url
        old_banner_url = movie.banner_url
        old_trailer_url = movie.trailer_url
        old_video_url = movie.video_url

        # ═══════════════════════════════════════════════════════════════
        # UPDATE FILES (CONCURRENT UPLOADS)
        # ═══════════════════════════════════════════════════════════════
        upload_tasks = []
        file_types = []
        
        if trailer_file:
            logger.info(f"📹 Replacing trailer: {trailer_file.filename}")
            upload_tasks.append(
                storage_service.upload_file(
                    trailer_file.file,
                    trailer_file.filename,
                    trailer_file.content_type or 'video/mp4',
                    file_category='trailer'
                )
            )
            file_types.append('trailer')
        
        if poster_file:
            logger.info(f"🖼️ Replacing poster: {poster_file.filename}")
            upload_tasks.append(
                storage_service.upload_file(
                    poster_file.file,
                    poster_file.filename,
                    poster_file.content_type or 'image/jpeg',
                    file_category='poster'
                )
            )
            file_types.append('poster')
        
        if banner_file:
            logger.info(f"🖼️ Replacing banner: {banner_file.filename}")
            upload_tasks.append(
                storage_service.upload_file(
                    banner_file.file,
                    banner_file.filename,
                    banner_file.content_type or 'image/jpeg',
                    file_category='banner'
                )
            )
            file_types.append('banner')
        
        # Upload new files concurrently
        if upload_tasks:
            results = await asyncio.gather(*upload_tasks, return_exceptions=True)
            
            # Update URLs based on successful uploads
            result_idx = 0
            for file_type in file_types:
                if not isinstance(results[result_idx], Exception) and results[result_idx]:
                    file_key, file_url = results[result_idx]
                    
                    if file_type == 'trailer':
                        movie.trailer_url = file_url
                        # Delete old trailer
                        if old_trailer_url and old_trailer_url != file_url:
                            try:
                                await storage_service.delete_file_by_url(old_trailer_url)
                                logger.info(f"🗑️ Deleted old trailer")
                            except Exception as e:
                                logger.warning(f"Failed to delete old trailer: {e}")
                    
                    elif file_type == 'poster':
                        movie.poster_url = file_url
                        # Delete old poster
                        if old_poster_url and old_poster_url != file_url:
                            try:
                                await storage_service.delete_file_by_url(old_poster_url)
                                logger.info(f"🗑️ Deleted old poster")
                            except Exception as e:
                                logger.warning(f"Failed to delete old poster: {e}")
                    
                    elif file_type == 'banner':
                        movie.banner_url = file_url
                        # Delete old banner
                        if old_banner_url and old_banner_url != file_url:
                            try:
                                await storage_service.delete_file_by_url(old_banner_url)
                                logger.info(f"🗑️ Deleted old banner")
                            except Exception as e:
                                logger.warning(f"Failed to delete old banner: {e}")
                
                result_idx += 1

        # ═══════════════════════════════════════════════════════════════
        # HANDLE VIDEO FILE (WITH HLS CONVERSION)
        # ═══════════════════════════════════════════════════════════════
        video_processing_job_id = None
        
        if video_file:
            if not video_file.content_type.startswith('video/'):
                raise HTTPException(status_code=400, detail="Video file must be a video format")
            
            logger.info(f"🎬 New video uploaded - starting HLS conversion")
            
            # Save video to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
            temp_video_path = temp_file.name
            
            try:
                chunk_size = 8192
                while True:
                    chunk = await video_file.read(chunk_size)
                    if not chunk:
                        break
                    temp_file.write(chunk)
                temp_file.close()
                
                # Generate job ID
                job_id = str(uuid.uuid4())
                video_processing_job_id = job_id
                
                # Store job status in Redis
                job_status = {
                    'status': VideoProcessingStatus.PENDING,
                    'progress': 0,
                    'message': 'Queued for HLS conversion',
                    'movie_id': movie_id,
                    'movie_title': movie.title
                }
                
                await redis_client.set(
                    f"{HLS_JOBS_KEY}:{job_id}",
                    job_status,
                    expire=86400
                )
                
                # Mark movie as inactive until processing completes
                movie.is_active = False
                
                # Start HLS processing in background
                asyncio.create_task(
                    process_movie_to_hls_background(
                        job_id,
                        movie_id,
                        temp_video_path,
                        old_video_url  # Pass old URL for cleanup
                    )
                )
                
                logger.info(f"✅ Video queued for HLS conversion: {job_id}")
                
            except Exception as e:
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to process video: {str(e)}"
                )

        # ═══════════════════════════════════════════════════════════════
        # UPDATE METADATA
        # ═══════════════════════════════════════════════════════════════
        if title is not None:
            movie.title = title
        if description is not None:
            movie.description = description
        if synopsis is not None:
            movie.synopsis = synopsis
        if duration is not None:
            movie.duration = duration
        if release_year is not None:
            movie.release_year = release_year
        if rating is not None:
            movie.rating = rating
        if content_rating is not None:
            movie.content_rating = content_rating
        if language is not None:
            movie.language = language
        if director is not None:
            movie.director = director
        if production is not None:
            movie.production = production
        if category_id is not None:
            movie.category_id = category_id
        if is_featured is not None:
            movie.is_featured = is_featured
        if is_active is not None and not video_file:  # Don't override if video is processing
            movie.is_active = is_active
        
        # Update cast
        if cast is not None:
            movie.cast = json.loads(cast) if cast else []
        
        # Update genres
        if genre_ids is not None:
            genre_ids_list = json.loads(genre_ids) if genre_ids else []
            if genre_ids_list:
                genre_result = await db.execute(
                    select(Genre).where(Genre.id.in_(genre_ids_list))
                )
                genres = genre_result.scalars().all()
                movie.genres = list(genres)
                logger.info(f"📚 Updated {len(genres)} genres")

        # Commit changes
        await db.commit()
        await db.refresh(movie)
        
        # Invalidate cache
        await redis_client.delete(f"movie:{movie_id}")
        await invalidate_movies_list_cache()
        
        logger.info(f"✅ Movie {movie_id} updated successfully")
        
        # Prepare response
        response_data = {
            "success": True,
            "message": "Movie updated successfully",
            "movie": await format_movie(movie, db)
        }
        
        # Add HLS job info if video is being processed
        if video_processing_job_id:
            response_data["hls_job"] = {
                "job_id": video_processing_job_id,
                "status_endpoint": f"/api/v1/movies/hls-status/{video_processing_job_id}",
                "estimated_time": "5-15 minutes depending on video length"
            }
            response_data["message"] = "Movie updated. New video is being converted to HLS format."
        
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error updating movie: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update movie: {str(e)}")        


# ==================== HELPER FUNCTIONS ====================

async def invalidate_movies_list_cache():
    """Invalidate all movies list cache entries"""
    try:
        # Get all keys matching pattern
        keys = await redis_client.keys("movies:list:*")
        if keys:
            for key in keys:
                await redis_client.delete(key)
            logger.info(f"🗑️ Invalidated {len(keys)} movie list cache entries")
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")


# ==================== BACKGROUND TASK (PROPERLY ASYNC) ====================

async def process_movie_to_hls_background(
    job_id: str,
    movie_id: int,
    video_path: str,
    old_video_url: Optional[str] = None  # 👈 ADD THIS
):
    """
    Background HLS conversion with Redis status updates
    """
    
    async def status_callback(update: dict):
        """Update job status in Redis"""
        try:
            current_status = await redis_client.get(f"{HLS_JOBS_KEY}:{job_id}") or {}
            current_status.update(update)
            
            await redis_client.set(
                f"{HLS_JOBS_KEY}:{job_id}",
                current_status,
                expire=86400
            )
            
            progress = update.get('progress', 0)
            message = update.get('message', '')
            
            if progress in [0, 5, 25, 50, 75, 95, 100]:
                logger.info(f"📊 Job {job_id[:8]}: {progress}% - {message}")
        except Exception as e:
            logger.error(f"Error updating status: {e}")

    try:
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"🎬 STARTING BACKGROUND JOB: {job_id[:8]}")
        logger.info(f"   Movie ID: {movie_id}")
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        result = await video_task_service.process_video_to_hls(
            video_id=movie_id,
            input_video_path=video_path,
            content_type='movie',
            callback=status_callback
        )

        if result['status'] == VideoProcessingStatus.COMPLETED:
            # Create new DB session for background task
            async with AsyncSessionLocal() as db_session:
                result_db = await db_session.execute(
                    select(Movie).where(Movie.id == movie_id)
                )
                movie = result_db.scalar_one_or_none()
                
                if movie:
                    movie.video_url = result['hls_url']
                    movie.duration = int(result['duration'])
                    movie.is_active = True
                    
                    await db_session.commit()
                    await db_session.refresh(movie)

                    logger.info(f"✅ Movie {movie_id} updated with HLS URL")
                    logger.info(f"   HLS URL: {result['hls_url']}")
                    logger.info(f"   Duration: {int(result['duration'])}s")
                    
                    # 👇 DELETE OLD VIDEO IF IT EXISTS
                    if old_video_url and 'hls/movies' in old_video_url:
                        try:
                            logger.info(f"🗑️ Deleting old HLS files")
                            await video_task_service.delete_hls_video(movie_id, 'movie')
                        except Exception as e:
                            logger.warning(f"Failed to delete old HLS files: {e}")
                    
                    # Update final status in Redis
                    final_status = {
                        'status': VideoProcessingStatus.COMPLETED,
                        'progress': 100,
                        'message': 'HLS conversion completed successfully!',
                        'movie_id': movie_id,
                        'movie_title': movie.title,
                        'result': {
                            'hls_url': result['hls_url'],
                            'duration': result['duration'],
                            'variants': result['variants'],
                            'total_size_mb': round(result['total_size_bytes'] / 1024 / 1024, 2),
                            'processing_time': result['processing_time_seconds']
                        }
                    }
                    
                    await redis_client.set(
                        f"{HLS_JOBS_KEY}:{job_id}",
                        final_status,
                        expire=86400
                    )
                    
                    # Invalidate movie cache
                    await redis_client.delete(f"movie:{movie_id}")
                    
                else:
                    logger.error(f"❌ Movie {movie_id} not found in database")
                    raise Exception(f"Movie {movie_id} not found after processing")

        else:
            raise Exception(result.get('error', 'Unknown processing error'))

    except Exception as e:
        logger.error(f"❌ HLS PROCESSING FAILED FOR MOVIE {movie_id}: {str(e)}")

        # Update failed status in Redis
        failed_status = {
            'status': VideoProcessingStatus.FAILED,
            'progress': 0,
            'message': f'Processing failed: {str(e)}',
            'movie_id': movie_id,
            'error': str(e)
        }
        
        await redis_client.set(
            f"{HLS_JOBS_KEY}:{job_id}",
            failed_status,
            expire=86400
        )

        try:
            async with AsyncSessionLocal() as db_session:
                result = await db_session.execute(
                    select(Movie).where(Movie.id == movie_id)
                )
                movie = result.scalar_one_or_none()
                
                if movie:
                    movie.is_active = False
                    movie.video_url = old_video_url  # 👈 RESTORE OLD VIDEO ON FAILURE
                    await db_session.commit()
                    logger.info(f"⚠️ Movie {movie_id} reverted to old video")
        except Exception as db_error:
            logger.error(f"❌ Failed to update movie status: {db_error}")

    finally:
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                logger.info(f"🗑️ Cleaned up temp file: {video_path}")
            except Exception as e:
                logger.error(f"Failed to cleanup temp file: {e}")
        
        logger.info(f"✅ Background job {job_id[:8]} completed")