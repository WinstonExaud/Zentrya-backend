# app/api/v1/episodes.py
"""
Episode Management with HLS Conversion + Redis Caching + Auto-Sync
- Async database operations
- Redis caching for faster loading
- HLS video processing for episodes
- Automatic series count synchronization
- Production-ready
"""

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update
import logging
import asyncio
import os
import io
from datetime import datetime

from ...database import get_async_db, AsyncSessionLocal
from ...redis_client import redis_client
from ...models import Episode, Series, User
from ...services.watch_time_service import watch_time_service
from ..deps import get_current_user, get_current_superuser
from ...utils.storage import storage_service
from ...services.video_tasks import video_task_service, VideoProcessingStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/series/{series_id}/episodes", tags=["episodes"])

# ==================== PYDANTIC MODELS ====================

class WatchStartRequest(BaseModel):
    device_id: Optional[str] = None


class WatchProgressRequest(BaseModel):
    session_id: str
    current_position_seconds: int
    quality_level: Optional[str] = None


class WatchEndRequest(BaseModel):
    session_id: str


class EpisodeBase(BaseModel):
    episode_number: int
    season_number: int
    title: str
    description: str
    duration: Optional[int] = None
    status: str = "draft"


class EpisodeCreate(EpisodeBase):
    series_id: int


class EpisodeUpdate(BaseModel):
    episode_number: Optional[int] = None
    season_number: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[int] = None
    status: Optional[str] = None
    view_count: Optional[int] = None


class EpisodeResponse(EpisodeBase):
    id: int
    series_id: int
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    view_count: int
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== HELPER FUNCTIONS ====================

def format_episode(episode: Episode) -> dict:
    """Format episode response"""
    return {
        "id": episode.id,
        "series_id": episode.series_id,
        "episode_number": episode.episode_number,
        "season_number": episode.season_number,
        "title": episode.title,
        "description": episode.description,
        "duration": episode.duration,
        "video_url": episode.video_url,
        "thumbnail_url": episode.thumbnail_url,
        "status": episode.status,
        "view_count": episode.view_count,
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
        "updated_at": episode.updated_at.isoformat() if episode.updated_at else None,
    }


async def invalidate_episode_cache(series_id: int):
    """Invalidate episode cache for a series"""
    try:
        keys = await redis_client.keys(f"episodes:series:{series_id}:*")
        if keys:
            for key in keys:
                await redis_client.delete(key)
            logger.info(f"🗑️ Invalidated {len(keys)} episode cache entries")
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")


# ==================== AUTO-SYNC HELPER ====================

async def sync_series_episode_counts(db: AsyncSession, series_id: int):
    """
    Sync series episode and season counts from Episode table
    Automatically called after creating/deleting episodes
    """
    try:
        # Count actual episodes
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
        
    except Exception as e:
        logger.error(f"❌ Error syncing series counts: {e}")
        raise


# ==================== LIST EPISODES ====================

@router.get("/", response_model=dict)
async def list_episodes(
    series_id: int,
    skip: int = 0,
    limit: int = 100,
    season_number: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """Get all episodes with pagination and filtering"""
    try:
        cache_key = f"episodes:series:{series_id}:skip={skip}:limit={limit}:season={season_number}:status={status}"
        
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.info(f"✅ Cache hit for episodes series {series_id}")
            return cached_data
        
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        query = select(Episode).where(Episode.series_id == series_id)

        if season_number is not None:
            query = query.where(Episode.season_number == season_number)
        
        if status is not None:
            query = query.where(Episode.status == status)

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()

        query = query.order_by(Episode.season_number, Episode.episode_number)
        query = query.offset(skip).limit(limit)

        result = await db.execute(query)
        episodes = result.scalars().all()

        response = {
            "episodes": [format_episode(episode) for episode in episodes],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
        
        await redis_client.set(cache_key, response, expire=120)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching episodes for series {series_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch episodes")


# ==================== CREATE EPISODE WITH HLS ====================

@router.post("/create-with-hls", status_code=status.HTTP_201_CREATED)
async def create_episode_with_hls(
    series_id: int,
    episode_number: int = Form(...),
    season_number: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    video_file: UploadFile = File(...),
    thumbnail_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Create episode with HLS conversion + Auto-sync series counts
    
    **Features:**
    - Uploads thumbnail to Firebase Storage
    - Processes video with HLS conversion (360p/480p/720p/1080p)
    - Automatically updates series total_episodes and total_seasons
    - Background processing with job tracking
    """
    try:
        logger.info(f"📺 Creating episode S{season_number}E{episode_number} for series {series_id}")
        
        # ═══════════════════════════════════════════════════════════
        # STEP 1: Verify series exists
        # ═══════════════════════════════════════════════════════════
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Series {series_id} not found"
            )
        
        # ═══════════════════════════════════════════════════════════
        # STEP 2: Check for duplicate episode
        # ═══════════════════════════════════════════════════════════
        existing_result = await db.execute(
            select(Episode).where(
                and_(
                    Episode.series_id == series_id,
                    Episode.season_number == season_number,
                    Episode.episode_number == episode_number
                )
            )
        )
        existing_episode = existing_result.scalar_one_or_none()
        
        if existing_episode:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Episode S{season_number}E{episode_number} already exists"
            )
        
        # ═══════════════════════════════════════════════════════════
        # STEP 3: Upload thumbnail to Firebase Storage
        # ═══════════════════════════════════════════════════════════
        thumbnail_url = None
        if thumbnail_file:
            logger.info(f"📤 Uploading thumbnail: {thumbnail_file.filename}")
            
            # Read file content and convert to BytesIO
            file_content = await thumbnail_file.read()
            file_obj = io.BytesIO(file_content)
            
            # Upload to Firebase Storage
            _, thumbnail_url = await storage_service.upload_file(
                file_obj,
                thumbnail_file.filename,
                thumbnail_file.content_type or 'image/jpeg',
                file_category='thumbnail'
            )
            logger.info(f"✅ Thumbnail uploaded: {thumbnail_url}")
        
        # ═══════════════════════════════════════════════════════════
        # STEP 4: Create episode in database (status: processing)
        # ═══════════════════════════════════════════════════════════
        new_episode = Episode(
            series_id=series_id,
            episode_number=episode_number,
            season_number=season_number,
            title=title,
            description=description,
            thumbnail_url=thumbnail_url,
            video_url=None,  # Will be set after HLS processing
            duration=1,
            view_count=0,
            status="processing"
        )
        
        db.add(new_episode)
        await db.commit()
        await db.refresh(new_episode)
        
        logger.info(f"✅ Episode created in DB: ID {new_episode.id}")
        
        # ═══════════════════════════════════════════════════════════
        # STEP 5: AUTO-SYNC series counts (NEW!)
        # ═══════════════════════════════════════════════════════════
        await sync_series_episode_counts(db, series_id)
        await db.commit()
        
        # Invalidate series cache
        await redis_client.delete(f"series:{series_id}")
        await invalidate_episode_cache(series_id)
        
        logger.info(f"✅ Series counts synced after episode creation")
        
        # ═══════════════════════════════════════════════════════════
        # STEP 6: Queue HLS conversion (background task)
        # ═══════════════════════════════════════════════════════════
        job_id = f"episode_{new_episode.id}_{int(datetime.utcnow().timestamp())}"
        temp_video_path = f"/tmp/episode_{new_episode.id}_{video_file.filename}"
        
        try:
            # Save video temporarily
            with open(temp_video_path, "wb") as buffer:
                content = await video_file.read()
                buffer.write(content)
            
            logger.info(f"✅ Video saved temporarily: {temp_video_path}")
            
            # Start background HLS processing
            asyncio.create_task(
                process_episode_hls_background(
                    episode_id=new_episode.id,
                    video_path=temp_video_path,
                    job_id=job_id
                )
            )
            
            logger.info(f"🎬 HLS conversion queued: {job_id}")
            
        except Exception as e:
            logger.error(f"❌ Error queuing HLS job: {e}")
            
            # Rollback episode creation
            await db.delete(new_episode)
            await sync_series_episode_counts(db, series_id)  # Re-sync after deletion
            await db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to queue video processing: {str(e)}"
            )
        
        # ═══════════════════════════════════════════════════════════
        # STEP 7: Return response with job tracking info
        # ═══════════════════════════════════════════════════════════
        return {
            "success": True,
            "message": "Episode created, video processing started",
            "episode": {
                "id": new_episode.id,
                "series_id": new_episode.series_id,
                "episode_number": new_episode.episode_number,
                "season_number": new_episode.season_number,
                "title": new_episode.title,
                "thumbnail_url": new_episode.thumbnail_url,
                "status": new_episode.status
            },
            "hls_job": {
                "job_id": job_id,
                "status_endpoint": f"/episodes/hls-status/{job_id}",
                "estimated_time": "5-10 minutes"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating episode: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create episode: {str(e)}"
        )


# ==================== BACKGROUND HLS PROCESSING ====================

async def process_episode_hls_background(episode_id: int, video_path: str, job_id: str):
    """
    Background task to process episode video into HLS format
    Converts to 360p, 480p, 720p, 1080p
    """
    try:
        logger.info(f"🎬 Starting HLS processing for episode {episode_id}")
        
        # Update job status
        await redis_client.set(
            f"hls_job:{job_id}",
            {
                "status": VideoProcessingStatus.PROCESSING,
                "progress": 0,
                "message": "Converting video to HLS format...",
                "episode_id": episode_id
            },
            expire=3600
        )
        
        # Progress callback
        async def progress_update(update: dict):
            try:
                await redis_client.set(
                    f"hls_job:{job_id}",
                    {
                        "status": update.get('status', VideoProcessingStatus.PROCESSING),
                        "progress": update.get('progress', 0),
                        "message": update.get('message', 'Processing...'),
                        "episode_id": episode_id,
                        "quality_progress": update.get('quality_progress', {})
                    },
                    expire=3600
                )
            except Exception as e:
                logger.warning(f"Failed to update progress: {e}")
        
        # Process video with video_task_service
        result = await video_task_service.process_video_to_hls(
            video_id=episode_id,
            input_video_path=video_path,
            content_type='episode',
            callback=progress_update
        )
        
        logger.info(f"✅ HLS processing complete: {result}")
        
        # Update episode in database
        async with AsyncSessionLocal() as session:
            episode_result = await session.execute(
                select(Episode).where(Episode.id == episode_id)
            )
            episode = episode_result.scalar_one_or_none()
            
            if episode:
                episode.video_url = result['hls_url']
                episode.duration = int(result['duration'] / 60)  # Convert to minutes
                episode.status = "published"
                episode.updated_at = datetime.utcnow()
                
                await session.commit()
                logger.info(f"✅ Episode {episode_id} updated with HLS URL")
        
        # Update job status to completed
        await redis_client.set(
            f"hls_job:{job_id}",
            {
                "status": VideoProcessingStatus.COMPLETED,
                "progress": 100,
                "message": "Video processing complete",
                "episode_id": episode_id,
                "result": {
                    "hls_url": result['hls_url'],
                    "duration": result['duration'],
                    "qualities": result.get('qualities', [])
                }
            },
            expire=3600
        )
        
        # Cleanup temporary file
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"✅ Temporary file cleaned up: {video_path}")
        except Exception as e:
            logger.warning(f"⚠️ Cleanup warning: {e}")
        
        logger.info(f"🎉 Episode {episode_id} HLS processing complete!")
        
    except Exception as e:
        logger.error(f"❌ HLS processing failed for episode {episode_id}: {e}")
        import traceback
        traceback.print_exc()
        
        # Update episode status to failed
        try:
            async with AsyncSessionLocal() as session:
                episode_result = await session.execute(
                    select(Episode).where(Episode.id == episode_id)
                )
                episode = episode_result.scalar_one_or_none()
                
                if episode:
                    episode.status = "failed"
                    await session.commit()
        except Exception as db_error:
            logger.error(f"Failed to update episode status: {db_error}")
        
        # Update job status to failed
        await redis_client.set(
            f"hls_job:{job_id}",
            {
                "status": VideoProcessingStatus.FAILED,
                "progress": 0,
                "message": f"Processing failed: {str(e)}",
                "episode_id": episode_id
            },
            expire=3600
        )
        
        # Cleanup
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
        except:
            pass


# ==================== HLS STATUS ====================

@router.get("/hls-status/{job_id}", status_code=status.HTTP_200_OK)
async def get_hls_processing_status(job_id: str):
    """
    Get HLS processing status for a job
    
    **Returns:**
    - status: processing, completed, failed
    - progress: 0-100
    - message: Current status message
    - quality_progress: Individual quality conversion progress
    """
    try:
        # Get status from Redis
        status_data = await redis_client.get(f"hls_job:{job_id}")
        
        if not status_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found or expired"
            )
        
        return {
            "success": True,
            "data": status_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching HLS status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch processing status"
        )


# ==================== UPDATE EPISODE ====================

@router.put("/{episode_id}")
async def update_episode(
    series_id: int,
    episode_id: int,
    episode_number: Optional[int] = Form(None),
    season_number: Optional[int] = Form(None),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    duration: Optional[int] = Form(None),
    status: Optional[str] = Form(None),
    thumbnail_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Update episode metadata (no video re-upload)
    Can update thumbnail image
    """
    try:
        # Verify series exists
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        # Get episode
        result = await db.execute(
            select(Episode).where(
                and_(Episode.id == episode_id, Episode.series_id == series_id)
            )
        )
        episode = result.scalar_one_or_none()
        
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")

        # Check episode number conflict
        if episode_number is not None and episode_number != episode.episode_number:
            check_season = season_number if season_number is not None else episode.season_number
            
            existing_result = await db.execute(
                select(Episode).where(
                    and_(
                        Episode.series_id == series_id,
                        Episode.season_number == check_season,
                        Episode.episode_number == episode_number,
                        Episode.id != episode_id
                    )
                )
            )
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Episode {episode_number} already exists in season {check_season}"
                )

        # Update text fields
        if episode_number is not None:
            episode.episode_number = episode_number
        if season_number is not None:
            episode.season_number = season_number
        if title is not None:
            episode.title = title
        if description is not None:
            episode.description = description
        if duration is not None:
            episode.duration = duration
        if status is not None:
            episode.status = status
        
        # ═══════════════════════════════════════════════════════════
        # Handle thumbnail upload (FIXED)
        # ═══════════════════════════════════════════════════════════
        if thumbnail_file:
            # Delete old thumbnail
            if episode.thumbnail_url:
                await storage_service.delete_file(episode.thumbnail_url, 'firebase')
            
            logger.info(f"🖼️ Uploading new thumbnail: {thumbnail_file.filename}")
            
            # Read file content and convert to BytesIO
            file_content = await thumbnail_file.read()
            file_obj = io.BytesIO(file_content)
            
            # Upload new thumbnail
            _, thumbnail_url = await storage_service.upload_file(
                file_obj,
                thumbnail_file.filename,
                thumbnail_file.content_type or 'image/jpeg',
                file_category='thumbnail'
            )
            episode.thumbnail_url = thumbnail_url

        episode.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(episode)
        
        # Invalidate cache
        await redis_client.delete(f"episode:{episode_id}")
        await invalidate_episode_cache(series_id)
        
        logger.info(f"✅ Episode updated: {episode.title}")
        
        return {
            "data": {
                "id": episode.id,
                "title": episode.title,
                "message": "Episode updated successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error updating episode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update episode")


# ==================== DELETE EPISODE ====================

@router.delete("/{episode_id}")
async def delete_episode(
    series_id: int,
    episode_id: int,
    hard_delete: bool = False,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Delete episode (soft or hard) + Auto-sync series counts
    
    **Soft delete:** Sets status to 'draft'
    **Hard delete:** Removes from database and deletes all files
    """
    try:
        # Verify series exists
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        # Get episode
        result = await db.execute(
            select(Episode).where(
                and_(Episode.id == episode_id, Episode.series_id == series_id)
            )
        )
        episode = result.scalar_one_or_none()
        
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")

        if hard_delete:
            episode_title = episode.title
            
            # ═══════════════════════════════════════════════════════════
            # Delete HLS files from R2 Storage
            # ═══════════════════════════════════════════════════════════
            if episode.video_url and 'hls/episodes' in episode.video_url:
                logger.info(f"🗑️ Deleting HLS files for episode {episode_id}")
                await video_task_service.delete_hls_video(episode_id, 'episode')
            
            # Delete thumbnail from Firebase
            if episode.thumbnail_url:
                await storage_service.delete_file(episode.thumbnail_url, 'firebase')
            
            # Delete from database
            await db.delete(episode)
            await db.commit()

            # ═══════════════════════════════════════════════════════════
            # AUTO-SYNC: Update series counts after deletion (NEW!)
            # ═══════════════════════════════════════════════════════════
            await sync_series_episode_counts(db, series_id)
            await db.commit()
            
            # Invalidate cache
            await redis_client.delete(f"episode:{episode_id}")
            await redis_client.delete(f"series:{series_id}")
            await invalidate_episode_cache(series_id)
            
            logger.info(f"✅ Episode permanently deleted: {episode_title}, series counts synced")
            
            return {
                "data": {
                    "message": f"Episode '{episode_title}' permanently deleted",
                    "series_synced": True
                }
            }
        else:
            # Soft delete - just change status
            episode.status = 'draft'
            await db.commit()
            
            # Invalidate cache
            await redis_client.delete(f"episode:{episode_id}")
            await invalidate_episode_cache(series_id)
            
            logger.info(f"✅ Episode soft deleted: {episode.title}")
            return {"data": {"message": "Episode deleted successfully"}}
    
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error deleting episode: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete episode")


# ==================== TRACK VIEW ====================

@router.post("/{episode_id}/track-view", status_code=status.HTTP_200_OK)
async def track_episode_view(
    series_id: int,
    episode_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """Track episode view - increment view count"""
    try:
        # Increment in Redis
        redis_key = f"episode:{episode_id}:views"
        await redis_client.increment(redis_key)
        
        # Update database
        await db.execute(
            update(Episode)
            .where(Episode.id == episode_id)
            .values(view_count=Episode.view_count + 1)
        )
        await db.commit()
        
        # Get updated count
        result = await db.execute(
            select(Episode.view_count, Episode.title).where(Episode.id == episode_id)
        )
        row = result.one_or_none()
        
        if not row:
            raise HTTPException(status_code=404, detail="Episode not found")
        
        view_count, title = row
        
        # Invalidate cache
        await redis_client.delete(f"episode:{episode_id}")
        
        logger.info(f"✅ View tracked: {title} (Total: {view_count})")
        
        return {
            "data": {
                "episode_id": episode_id,
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


# ==================== SEASONS LIST ====================

@router.get("/seasons/list")
async def get_seasons_list(
    series_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """Get list of all seasons with episode counts"""
    try:
        cache_key = f"series:{series_id}:seasons"
        cached_seasons = await redis_client.get(cache_key)
        
        if cached_seasons:
            logger.info(f"✅ Cache hit for seasons series {series_id}")
            return cached_seasons
        
        # Verify series exists
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        # Get distinct seasons
        seasons_result = await db.execute(
            select(Episode.season_number)
            .where(Episode.series_id == series_id)
            .distinct()
            .order_by(Episode.season_number)
        )
        seasons = seasons_result.scalars().all()
        
        # Get episode counts per season
        season_stats = []
        for season in seasons:
            total_result = await db.execute(
                select(func.count(Episode.id)).where(
                    and_(Episode.series_id == series_id, Episode.season_number == season)
                )
            )
            total_episodes = total_result.scalar() or 0
            
            published_result = await db.execute(
                select(func.count(Episode.id)).where(
                    and_(
                        Episode.series_id == series_id,
                        Episode.season_number == season,
                        Episode.status == 'published'
                    )
                )
            )
            published_episodes = published_result.scalar() or 0
            
            season_stats.append({
                "season_number": season,
                "total_episodes": total_episodes,
                "published_episodes": published_episodes
            })

        response = {
            "seasons": list(seasons),
            "season_stats": season_stats
        }
        
        await redis_client.set(cache_key, response, expire=300)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching seasons: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch seasons")


# ==================== SEASON STATS ====================

@router.get("/stats/season/{season_number}")
async def get_season_stats(
    series_id: int,
    season_number: int,
    db: AsyncSession = Depends(get_async_db)
):
    """Get statistics for a specific season"""
    try:
        cache_key = f"series:{series_id}:season:{season_number}:stats"
        cached_stats = await redis_client.get(cache_key)
        
        if cached_stats:
            logger.info(f"✅ Cache hit for season stats")
            return cached_stats
        
        # Verify series exists
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        # Execute queries sequentially
        total_result = await db.execute(
            select(func.count(Episode.id)).where(
                and_(Episode.series_id == series_id, Episode.season_number == season_number)
            )
        )
        total_episodes = total_result.scalar() or 0
        
        published_result = await db.execute(
            select(func.count(Episode.id)).where(
                and_(
                    Episode.series_id == series_id,
                    Episode.season_number == season_number,
                    Episode.status == 'published'
                )
            )
        )
        published_episodes = published_result.scalar() or 0
        
        draft_result = await db.execute(
            select(func.count(Episode.id)).where(
                and_(
                    Episode.series_id == series_id,
                    Episode.season_number == season_number,
                    Episode.status == 'draft'
                )
            )
        )
        draft_episodes = draft_result.scalar() or 0
        
        processing_result = await db.execute(
            select(func.count(Episode.id)).where(
                and_(
                    Episode.series_id == series_id,
                    Episode.season_number == season_number,
                    Episode.status == 'processing'
                )
            )
        )
        processing_episodes = processing_result.scalar() or 0
        
        views_result = await db.execute(
            select(func.sum(Episode.view_count)).where(
                and_(Episode.series_id == series_id, Episode.season_number == season_number)
            )
        )
        total_views = int(views_result.scalar() or 0)
        
        duration_result = await db.execute(
            select(func.sum(Episode.duration)).where(
                and_(Episode.series_id == series_id, Episode.season_number == season_number)
            )
        )
        total_duration = int(duration_result.scalar() or 0)

        stats = {
            "season_number": season_number,
            "total_episodes": total_episodes,
            "published_episodes": published_episodes,
            "draft_episodes": draft_episodes,
            "processing_episodes": processing_episodes,
            "total_views": total_views,
            "total_duration": total_duration
        }
        
        await redis_client.set(cache_key, stats, expire=300)
        
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching season stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch season stats")


# ==================== WATCH TIME TRACKING ====================

@router.post("/{episode_id}/watch/start", status_code=status.HTTP_200_OK)
async def start_episode_watch_session(
    series_id: int,
    episode_id: int,
    request: WatchStartRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """Start episode watch session for analytics"""
    try:
        result = await db.execute(
            select(Episode).where(
                and_(Episode.id == episode_id, Episode.series_id == series_id)
            )
        )
        episode = result.scalar_one_or_none()
        
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        
        if not episode.duration:
            raise HTTPException(
                status_code=400,
                detail="Episode duration not set. Cannot track watch-time."
            )
        
        session_data = await watch_time_service.start_episode_watch_session(
            db=db,
            user_id=current_user.id,
            series_id=series_id,
            episode_id=episode_id,
            video_duration=episode.duration,
            device_id=request.device_id
        )
        
        series_result = await db.execute(select(Series).where(Series.id == series_id))
        series = series_result.scalar_one_or_none()
        
        return {
            "success": True,
            "data": {
                **session_data,
                "series_title": series.title if series else None,
                "episode_title": episode.title,
                "episode_code": f"S{episode.season_number:02d}E{episode.episode_number:02d}",
                "video_duration_seconds": episode.duration,
                "message": "Watch session started successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error starting watch session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start watch session: {str(e)}")


@router.post("/{episode_id}/watch/progress", status_code=status.HTTP_200_OK)
async def update_episode_watch_progress(
    series_id: int,
    episode_id: int,
    request: WatchProgressRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """Update episode watch progress"""
    try:
        progress_data = await watch_time_service.update_watch_progress(
            db=db,
            session_id=request.session_id,
            current_position_seconds=request.current_position_seconds,
            quality_level=request.quality_level
        )
        
        return {"success": True, "data": progress_data}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error updating watch progress: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update progress: {str(e)}")


@router.post("/{episode_id}/watch/end", status_code=status.HTTP_200_OK)
async def end_episode_watch_session(
    series_id: int,
    episode_id: int,
    request: WatchEndRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """End episode watch session"""
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


@router.get("/{episode_id}/analytics", status_code=status.HTTP_200_OK)
async def get_episode_analytics(
    series_id: int,
    episode_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get detailed episode analytics (ADMIN ONLY)
    
    **Returns:**
    - View counts
    - Watch time statistics
    - Completion rates
    - Quality preferences
    - Drop-off points
    """
    try:
        analytics_data = await watch_time_service.get_episode_analytics(
            db=db,
            episode_id=episode_id
        )
        
        return {"success": True, "data": analytics_data}
        
    except Exception as e:
        logger.error(f"❌ Error getting episode analytics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")