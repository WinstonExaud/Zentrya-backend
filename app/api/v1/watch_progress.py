from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from pydantic import BaseModel
from datetime import datetime
import logging

from ...database import get_db
from ...models.user import User
from ...models.watch_progress import  WatchProgress
from ...models import Movie, Episode, Series  # ✅ FIXED: Import from models directly
from ...api.deps import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


class WatchProgressUpdate(BaseModel):
    current_time: float
    duration: float


class WatchProgressResponse(BaseModel):
    id: int
    user_id: int
    movie_id: int | None
    series_id: int | None
    episode_id: int | None
    current_time: float
    duration: float
    percentage_watched: float
    is_completed: bool
    last_watched: str
    
    # Include content details
    content_title: str | None = None
    content_poster: str | None = None
    content_type: str | None = None


@router.get("/continue-watching", response_model=List[WatchProgressResponse])
def get_continue_watching(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get continue watching list for user
    Returns incomplete content (watched < 95% and > 5%)
    """
    try:
        # Get watch progress for movies and episodes
        progress_items = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.percentage_watched >= 5,  # At least 5% watched
            WatchProgress.percentage_watched < 95,  # Less than 95% watched
        ).order_by(desc(WatchProgress.last_watched)).limit(limit).all()
        
        result = []
        for progress in progress_items:
            content_title = None
            content_poster = None
            content_type = None
            
            if progress.movie_id:
                # ✅ FIXED: Query movie directly
                movie = db.query(Movie).filter(Movie.id == progress.movie_id).first()
                if movie:
                    content_title = movie.title
                    content_poster = movie.poster_url
                    content_type = "movie"
            elif progress.episode_id:
                # ✅ FIXED: Query episode directly
                episode = db.query(Episode).filter(Episode.id == progress.episode_id).first()
                if episode:
                    series = db.query(Series).filter(Series.id == episode.series_id).first()
                    content_title = f"{series.title} - S{episode.season_number}E{episode.episode_number}" if series else f"Episode {episode.episode_number}"
                    content_poster = episode.thumbnail_url or (series.poster_url if series else None)
                    content_type = "episode"
            
            result.append(WatchProgressResponse(
                id=progress.id,
                user_id=progress.user_id,
                movie_id=progress.movie_id,
                series_id=progress.series_id,
                episode_id=progress.episode_id,
                current_time=progress.current_time,
                duration=progress.duration,
                percentage_watched=progress.percentage_watched,
                is_completed=progress.is_completed,
                last_watched=progress.last_watched.isoformat(),
                content_title=content_title,
                content_poster=content_poster,
                content_type=content_type,
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching continue watching: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch continue watching"
        )


@router.get("/movie/{movie_id}")
def get_movie_progress(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get watch progress for a specific movie
    """
    try:
        progress = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.movie_id == movie_id
        ).first()
        
        if not progress:
            return {
                "current_time": 0,
                "duration": 0,
                "percentage_watched": 0,
                "is_completed": False
            }
        
        return {
            "id": progress.id,
            "current_time": progress.current_time,
            "duration": progress.duration,
            "percentage_watched": progress.percentage_watched,
            "is_completed": progress.is_completed,
            "last_watched": progress.last_watched.isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Error fetching movie progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch progress"
        )


@router.post("/movie/{movie_id}")
def update_movie_progress(
    movie_id: int,
    progress_data: WatchProgressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update or create watch progress for a movie
    Automatically marks as completed if watched >= 70%
    Updates view count if first time reaching 70%
    """
    try:
        # Calculate percentage
        percentage = (progress_data.current_time / progress_data.duration * 100) if progress_data.duration > 0 else 0
        
        # Check if progress exists
        progress = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.movie_id == movie_id
        ).first()
        
        was_completed_before = progress.is_completed if progress else False
        is_now_completed = percentage >= 70
        
        if progress:
            # Update existing progress
            progress.current_time = progress_data.current_time
            progress.duration = progress_data.duration
            progress.percentage_watched = percentage
            progress.is_completed = is_now_completed
            progress.last_watched = datetime.utcnow()
        else:
            # Create new progress
            progress = WatchProgress(
                user_id=current_user.id,
                movie_id=movie_id,
                current_time=progress_data.current_time,
                duration=progress_data.duration,
                percentage_watched=percentage,
                is_completed=is_now_completed,
                last_watched=datetime.utcnow(),
            )
            db.add(progress)
        
        # ✅ FIXED: Import already at top
        # Update movie view count if reached 70% for first time
        if is_now_completed and not was_completed_before:
            movie = db.query(Movie).filter(Movie.id == movie_id).first()
            if movie:
                movie.view_count = (movie.view_count or 0) + 1
                logger.info(f"✅ Movie {movie_id} view count incremented to {movie.view_count}")
        
        db.commit()
        db.refresh(progress)
        
        return {
            "message": "Progress updated successfully",
            "current_time": progress.current_time,
            "percentage_watched": progress.percentage_watched,
            "is_completed": progress.is_completed,
        }
        
    except Exception as e:
        logger.error(f"Error updating movie progress: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update progress"
        )


@router.delete("/movie/{movie_id}")
def delete_movie_progress(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete watch progress for a movie
    """
    try:
        progress = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.movie_id == movie_id
        ).first()
        
        if progress:
            db.delete(progress)
            db.commit()
            return {"message": "Progress deleted successfully"}
        
        return {"message": "No progress found"}
        
    except Exception as e:
        logger.error(f"Error deleting progress: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete progress"
        )


# Similar endpoints for episodes
@router.get("/episode/{episode_id}")
def get_episode_progress(
    episode_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get watch progress for a specific episode"""
    try:
        progress = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.episode_id == episode_id
        ).first()
        
        if not progress:
            return {
                "current_time": 0,
                "duration": 0,
                "percentage_watched": 0,
                "is_completed": False
            }
        
        return {
            "id": progress.id,
            "current_time": progress.current_time,
            "duration": progress.duration,
            "percentage_watched": progress.percentage_watched,
            "is_completed": progress.is_completed,
            "last_watched": progress.last_watched.isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Error fetching episode progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch progress"
        )


@router.post("/episode/{episode_id}")
def update_episode_progress(
    episode_id: int,
    progress_data: WatchProgressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update or create watch progress for an episode
    """
    try:
        percentage = (progress_data.current_time / progress_data.duration * 100) if progress_data.duration > 0 else 0
        
        progress = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.episode_id == episode_id
        ).first()
        
        was_completed_before = progress.is_completed if progress else False
        is_now_completed = percentage >= 70
        
        if progress:
            progress.current_time = progress_data.current_time
            progress.duration = progress_data.duration
            progress.percentage_watched = percentage
            progress.is_completed = is_now_completed
            progress.last_watched = datetime.utcnow()
        else:
            # ✅ FIXED: Import already at top
            # Get series_id from episode
            episode = db.query(Episode).filter(Episode.id == episode_id).first()
            
            progress = WatchProgress(
                user_id=current_user.id,
                episode_id=episode_id,
                current_time=progress_data.current_time,
                duration=progress_data.duration,
                percentage_watched=percentage,
                is_completed=is_now_completed,
                last_watched=datetime.utcnow(),
            )
            db.add(progress)
        
        # ✅ FIXED: Import already at top
        # Update episode view count if reached 70% for first time
        if is_now_completed and not was_completed_before:
            episode = db.query(Episode).filter(Episode.id == episode_id).first()
            if episode:
                episode.view_count = (episode.view_count or 0) + 1
                logger.info(f"✅ Episode {episode_id} view count incremented")
        
        db.commit()
        db.refresh(progress)
        
        return {
            "message": "Progress updated successfully",
            "current_time": progress.current_time,
            "percentage_watched": progress.percentage_watched,
            "is_completed": progress.is_completed,
        }
        
    except Exception as e:
        logger.error(f"Error updating episode progress: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update progress"
        )


@router.delete("/episode/{episode_id}")
def delete_episode_progress(
    episode_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete watch progress for an episode
    """
    try:
        progress = db.query(WatchProgress).filter(
            WatchProgress.user_id == current_user.id,
            WatchProgress.episode_id == episode_id
        ).first()
        
        if progress:
            db.delete(progress)
            db.commit()
            return {"message": "Progress deleted successfully"}
        
        return {"message": "No progress found"}
        
    except Exception as e:
        logger.error(f"Error deleting episode progress: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete progress"
        )