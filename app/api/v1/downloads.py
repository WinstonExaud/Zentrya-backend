# backend/app/api/endpoints/downloads.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
import logging
import os
import requests
from pathlib import Path

from ...database import get_db
from ...models.user import User, UserDownload
from ...models.movie import Movie
from ...models.series import Series, Episode
from ...api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Download directory configuration
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/app/downloads")
Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)


# ==================== Download Models ====================

class DownloadCreate(BaseModel):
    movie_id: Optional[int] = None
    series_id: Optional[int] = None
    episode_id: Optional[int] = None
    quality: str  # low, medium, standard, high

class DownloadUpdate(BaseModel):
    status: str
    progress: Optional[float] = None
    downloaded_size: Optional[int] = None
    total_size: Optional[int] = None

class DownloadResponse(BaseModel):
    id: int
    user_id: int
    movie_id: Optional[int] = None
    series_id: Optional[int] = None
    episode_id: Optional[int] = None
    content_title: str
    content_poster: Optional[str] = None
    content_type: str
    quality: str
    status: str
    progress: float
    downloaded_size: int
    total_size: int
    download_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None

class DownloadListResponse(BaseModel):
    downloads: List[DownloadResponse]
    total: int
    total_size: int

class MessageResponse(BaseModel):
    message: str


# ==================== Background Download Task ====================

async def download_video_file(
    download_id: int,
    video_url: str,
    output_path: str,
    db_session
):
    """
    Background task to download video file with progress tracking.
    """
    try:
        # Get download record
        download = db_session.query(UserDownload).filter(
            UserDownload.id == download_id
        ).first()
        
        if not download:
            logger.error(f"Download {download_id} not found")
            return
        
        # Update status to downloading
        download.status = 'downloading'
        download.updated_at = datetime.utcnow()
        db_session.commit()
        
        logger.info(f"🔽 Starting download: {video_url} -> {output_path}")
        
        # Download with progress tracking
        response = requests.get(video_url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        if total_size == 0:
            total_size = download.total_size or estimate_file_size(None, download.quality)
        
        download.total_size = total_size
        db_session.commit()
        
        downloaded_size = 0
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    # Check if download was paused
                    db_session.refresh(download)
                    if download.status == 'paused':
                        logger.info(f"Download paused: {download_id}")
                        return
                    
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # Update progress every 1MB
                    if downloaded_size % (1024 * 1024) < 8192:
                        progress = (downloaded_size / total_size) * 100 if total_size > 0 else 0
                        download.progress = progress
                        download.downloaded_size = downloaded_size
                        download.updated_at = datetime.utcnow()
                        db_session.commit()
        
        # Mark as completed
        download.status = 'completed'
        download.progress = 100.0
        download.downloaded_size = downloaded_size
        download.download_path = output_path
        download.expires_at = datetime.utcnow() + timedelta(days=30)
        download.updated_at = datetime.utcnow()
        db_session.commit()
        
        logger.info(f"✅ Download completed: {output_path}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Download failed (network): {str(e)}")
        download.status = 'failed'
        download.updated_at = datetime.utcnow()
        db_session.commit()
        
    except Exception as e:
        logger.error(f"❌ Download failed: {str(e)}")
        import traceback
        traceback.print_exc()
        
        download.status = 'failed'
        download.updated_at = datetime.utcnow()
        db_session.commit()
        
        # Clean up partial file
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass


# ==================== Download Endpoints ====================

@router.get("/list", response_model=DownloadListResponse)
def get_user_downloads(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all downloads for the current user."""
    try:
        query = db.query(UserDownload).filter(
            UserDownload.user_id == current_user.id
        )
        
        if status_filter:
            query = query.filter(UserDownload.status == status_filter)
        
        downloads = query.order_by(UserDownload.created_at.desc()).all()
        
        download_list = []
        total_size = 0
        
        for download in downloads:
            content_title = "Unknown"
            content_poster = None
            content_type = "movie"
            
            if download.movie_id:
                movie = db.query(Movie).filter(Movie.id == download.movie_id).first()
                if movie:
                    content_title = movie.title
                    content_poster = movie.poster_url
                    content_type = "movie"
            elif download.episode_id:
                episode = db.query(Episode).filter(Episode.id == download.episode_id).first()
                if episode:
                    content_title = f"{episode.title}"
                    content_poster = episode.thumbnail_url
                    content_type = "episode"
                    if episode.series_id:
                        series = db.query(Series).filter(Series.id == episode.series_id).first()
                        if series:
                            content_title = f"{series.title} - S{episode.season_number}E{episode.episode_number}"
                            content_poster = series.poster_url or episode.thumbnail_url
            
            total_size += download.total_size or 0
            
            download_list.append({
                "id": download.id,
                "user_id": download.user_id,
                "movie_id": download.movie_id,
                "series_id": download.series_id,
                "episode_id": download.episode_id,
                "content_title": content_title,
                "content_poster": content_poster,
                "content_type": content_type,
                "quality": download.quality,
                "status": download.status,
                "progress": download.progress,
                "downloaded_size": download.downloaded_size,
                "total_size": download.total_size,
                "download_path": download.download_path,
                "created_at": download.created_at,
                "updated_at": download.updated_at,
                "expires_at": download.expires_at
            })
        
        return {
            "downloads": download_list,
            "total": len(download_list),
            "total_size": total_size
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get downloads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve downloads: {str(e)}"
        )


@router.post("/create", response_model=DownloadResponse)
async def create_download(
    download_data: DownloadCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new download and start downloading the video file."""
    try:
        # Validate input
        if not download_data.movie_id and not download_data.episode_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either movie_id or episode_id is required"
            )
        
        # Check if already exists
        existing = db.query(UserDownload).filter(
            UserDownload.user_id == current_user.id
        )
        
        if download_data.movie_id:
            existing = existing.filter(UserDownload.movie_id == download_data.movie_id)
        elif download_data.episode_id:
            existing = existing.filter(UserDownload.episode_id == download_data.episode_id)
        
        existing = existing.filter(
            UserDownload.status.in_(['downloading', 'completed', 'pending', 'paused'])
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This content is already downloaded or downloading"
            )
        
        # Get content details
        video_url = None
        content_title = "Unknown"
        content_poster = None
        total_size = 0
        series_id = None
        file_extension = "mp4"
        
        if download_data.movie_id:
            movie = db.query(Movie).filter(Movie.id == download_data.movie_id).first()
            if not movie:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Movie not found"
                )
            content_title = movie.title
            content_poster = movie.poster_url
            video_url = movie.video_url
            total_size = estimate_file_size(movie.duration, download_data.quality)
            
        elif download_data.episode_id:
            episode = db.query(Episode).filter(Episode.id == download_data.episode_id).first()
            if not episode:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Episode not found"
                )
            content_title = episode.title
            content_poster = episode.thumbnail_url
            video_url = episode.video_url
            series_id = episode.series_id
            total_size = estimate_file_size(episode.duration, download_data.quality)
        
        if not video_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video URL not available for this content"
            )
        
        # Convert relative URL to absolute if needed
        if not video_url.startswith('http'):
            base_url = os.getenv("API_BASE_URL", "http://192.168.43.186:8000")
            video_url = f"{base_url}{video_url}"
        
        # Generate unique filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in content_title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_title}_{download_data.quality}_{timestamp}.{file_extension}"
        
        # Create user-specific download directory
        user_dir = os.path.join(DOWNLOAD_DIR, str(current_user.id))
        Path(user_dir).mkdir(parents=True, exist_ok=True)
        
        output_path = os.path.join(user_dir, filename)
        
        # Create download record
        new_download = UserDownload(
            user_id=current_user.id,
            movie_id=download_data.movie_id,
            series_id=series_id,
            episode_id=download_data.episode_id,
            quality=download_data.quality,
            status='pending',
            progress=0.0,
            downloaded_size=0,
            total_size=total_size,
            video_url=video_url,
            download_path=output_path,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(new_download)
        db.commit()
        db.refresh(new_download)
        
        logger.info(f"✅ Download record created: {content_title} (ID: {new_download.id})")
        
        # Start background download task
        background_tasks.add_task(
            download_video_file,
            new_download.id,
            video_url,
            output_path,
            db
        )
        
        return {
            "id": new_download.id,
            "user_id": new_download.user_id,
            "movie_id": new_download.movie_id,
            "series_id": new_download.series_id,
            "episode_id": new_download.episode_id,
            "content_title": content_title,
            "content_poster": content_poster,
            "content_type": "movie" if download_data.movie_id else "episode",
            "quality": new_download.quality,
            "status": new_download.status,
            "progress": new_download.progress,
            "downloaded_size": new_download.downloaded_size,
            "total_size": new_download.total_size,
            "download_path": new_download.download_path,
            "created_at": new_download.created_at,
            "updated_at": new_download.updated_at,
            "expires_at": new_download.expires_at
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to create download: {str(e)}")
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create download: {str(e)}"
        )


@router.post("/{download_id}/pause", response_model=MessageResponse)
def pause_download(
    download_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pause an active download."""
    try:
        download = db.query(UserDownload).filter(
            UserDownload.id == download_id,
            UserDownload.user_id == current_user.id
        ).first()
        
        if not download:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Download not found"
            )
        
        if download.status != 'downloading':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Download is not active"
            )
        
        download.status = 'paused'
        download.updated_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"⏸️ Download paused: {download_id}")
        
        return {"message": "Download paused successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to pause download: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause download: {str(e)}"
        )


@router.post("/{download_id}/resume", response_model=MessageResponse)
async def resume_download(
    download_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resume a paused download."""
    try:
        download = db.query(UserDownload).filter(
            UserDownload.id == download_id,
            UserDownload.user_id == current_user.id
        ).first()
        
        if not download:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Download not found"
            )
        
        if download.status not in ['paused', 'failed']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Download cannot be resumed"
            )
        
        # Update status and restart download
        download.status = 'pending'
        download.updated_at = datetime.utcnow()
        db.commit()
        
        # Restart background download
        background_tasks.add_task(
            download_video_file,
            download.id,
            download.video_url,
            download.download_path,
            db
        )
        
        logger.info(f"▶️ Download resumed: {download_id}")
        
        return {"message": "Download resumed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to resume download: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume download: {str(e)}"
        )


@router.delete("/{download_id}", response_model=MessageResponse)
def delete_download(
    download_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a download and remove the file."""
    try:
        download = db.query(UserDownload).filter(
            UserDownload.id == download_id,
            UserDownload.user_id == current_user.id
        ).first()
        
        if not download:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Download not found"
            )
        
        # Delete file from disk
        if download.download_path and os.path.exists(download.download_path):
            try:
                os.remove(download.download_path)
                logger.info(f"🗑️ Deleted file: {download.download_path}")
            except Exception as e:
                logger.error(f"Failed to delete file: {e}")
        
        db.delete(download)
        db.commit()
        
        logger.info(f"✅ Download deleted: {download_id}")
        
        return {"message": "Download deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete download: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete download: {str(e)}"
        )


@router.delete("/clear/all", response_model=MessageResponse)
def clear_all_downloads(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear all completed and failed downloads."""
    try:
        downloads = db.query(UserDownload).filter(
            UserDownload.user_id == current_user.id,
            UserDownload.status.in_(['completed', 'failed'])
        ).all()
        
        deleted_count = 0
        
        for download in downloads:
            # Delete file from disk
            if download.download_path and os.path.exists(download.download_path):
                try:
                    os.remove(download.download_path)
                except Exception as e:
                    logger.error(f"Failed to delete file: {e}")
            
            db.delete(download)
            deleted_count += 1
        
        db.commit()
        
        logger.info(f"✅ Cleared {deleted_count} downloads")
        
        return {"message": f"Cleared {deleted_count} downloads"}
        
    except Exception as e:
        logger.error(f"❌ Failed to clear downloads: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear downloads: {str(e)}"
        )


@router.get("/{download_id}/serve")
def serve_download(
    download_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve the downloaded video file for offline playback."""
    try:
        download = db.query(UserDownload).filter(
            UserDownload.id == download_id,
            UserDownload.user_id == current_user.id
        ).first()
        
        if not download:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Download not found"
            )
        
        if download.status != 'completed':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Download is not completed yet"
            )
        
        if not download.download_path or not os.path.exists(download.download_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Downloaded file not found"
            )
        
        return FileResponse(
            path=download.download_path,
            media_type="video/mp4",
            filename=os.path.basename(download.download_path)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to serve download: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to serve download: {str(e)}"
        )


# ==================== Helper Functions ====================

def estimate_file_size(duration: Optional[int], quality: str) -> int:
    """Estimate file size based on duration and quality."""
    if not duration:
        duration = 5400  # Default 90 minutes
    
    bitrates = {
        'low': 500,
        'medium': 1000,
        'standard': 2500,
        'high': 5000
    }
    
    bitrate = bitrates.get(quality, 2500)
    size_mb = (bitrate * duration) / 8 / 1024
    size_bytes = int(size_mb * 1024 * 1024)
    
    return size_bytes