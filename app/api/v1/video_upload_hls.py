"""
HLS Video Upload Endpoint
Upload videos and automatically convert to HLS for adaptive streaming
"""

import os
import tempfile
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from ...database import get_db
from ...services.video_tasks import video_task_service, VideoProcessingStatus
from ...utils.storage import storage_service
from ...models.movie import Movie
from ...models.series import Episode
from ..deps import get_current_admin_user

logger = logging.getLogger(__name__)

router = APIRouter()


# In-memory job status tracker (use Redis in production)
processing_jobs = {}


@router.post("/upload-hls-video", tags=["HLS Video Upload"])
async def upload_video_for_hls_processing(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    content_type: str = Form(...),  # 'movie' or 'episode'
    content_id: int = Form(...),     # movie_id or episode_id
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    Upload video and process to HLS format

    **Process:**
    1. Upload original MP4 to temporary location
    2. Queue HLS transcoding job
    3. Return job ID for status tracking

    **Args:**
    - video: MP4 video file
    - content_type: 'movie' or 'episode'
    - content_id: ID of the movie or episode

    **Returns:**
    - job_id: UUID for tracking processing status
    - message: Status message
    """

    try:
        # Validate content type
        if content_type not in ['movie', 'episode']:
            raise HTTPException(status_code=400, detail="content_type must be 'movie' or 'episode'")

        # Validate file type
        if not video.content_type.startswith('video/'):
            raise HTTPException(status_code=400, detail="File must be a video")

        # Verify content exists in database
        if content_type == 'movie':
            content = db.query(Movie).filter(Movie.id == content_id).first()
            if not content:
                raise HTTPException(status_code=404, detail=f"Movie {content_id} not found")
        else:  # episode
            content = db.query(Episode).filter(Episode.id == content_id).first()
            if not content:
                raise HTTPException(status_code=404, detail=f"Episode {content_id} not found")

        logger.info(f"📤 Uploading video for {content_type} {content_id}")

        # Save uploaded video to temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        temp_video_path = temp_file.name

        try:
            # Write uploaded video to temp file
            chunk_size = 8192
            while True:
                chunk = await video.read(chunk_size)
                if not chunk:
                    break
                temp_file.write(chunk)

            temp_file.close()

            # Generate job ID
            job_id = str(uuid.uuid4())

            # Initialize job status
            processing_jobs[job_id] = {
                'status': VideoProcessingStatus.PENDING,
                'progress': 0,
                'message': 'Queued for processing',
                'content_type': content_type,
                'content_id': content_id
            }

            # Queue HLS processing in background
            background_tasks.add_task(
                process_video_background,
                job_id,
                content_id,
                temp_video_path,
                content_type,
                db
            )

            logger.info(f"✅ Video uploaded, processing queued with job_id: {job_id}")

            return {
                'success': True,
                'job_id': job_id,
                'message': f'Video upload successful. Processing started.',
                'status_endpoint': f'/api/v1/video/processing-status/{job_id}'
            }

        except Exception as e:
            # Cleanup temp file on error
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/processing-status/{job_id}", tags=["HLS Video Upload"])
async def get_processing_status(job_id: str):
    """
    Get HLS processing status

    **Returns:**
    - status: pending, processing, completed, or failed
    - progress: 0-100
    - message: Status message
    - result: HLS URLs (if completed)
    """

    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return processing_jobs[job_id]


@router.post("/convert-existing-video", tags=["HLS Video Upload"])
async def convert_existing_video_to_hls(
    background_tasks: BackgroundTasks,
    content_type: str = Form(...),  # 'movie' or 'episode'
    content_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    Convert existing MP4 video to HLS format

    **Use this if you already have videos uploaded but want to convert them to HLS**

    **Args:**
    - content_type: 'movie' or 'episode'
    - content_id: ID of the movie or episode

    **Returns:**
    - job_id: UUID for tracking processing status
    """

    try:
        # Get existing video URL
        if content_type == 'movie':
            content = db.query(Movie).filter(Movie.id == content_id).first()
            if not content:
                raise HTTPException(status_code=404, detail=f"Movie {content_id} not found")
            video_url = content.video_url
        else:
            content = db.query(Episode).filter(Episode.id == content_id).first()
            if not content:
                raise HTTPException(status_code=404, detail=f"Episode {content_id} not found")
            video_url = content.video_url

        if not video_url:
            raise HTTPException(status_code=400, detail="No video URL found for this content")

        # Generate job ID
        job_id = str(uuid.uuid4())

        # Initialize job status
        processing_jobs[job_id] = {
            'status': VideoProcessingStatus.PENDING,
            'progress': 0,
            'message': 'Queued for processing',
            'content_type': content_type,
            'content_id': content_id
        }

        # Queue processing
        background_tasks.add_task(
            process_existing_video_background,
            job_id,
            content_id,
            video_url,
            content_type,
            db
        )

        return {
            'success': True,
            'job_id': job_id,
            'message': 'Video queued for HLS conversion',
            'status_endpoint': f'/api/v1/video/processing-status/{job_id}'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Conversion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_video_background(
    job_id: str,
    content_id: int,
    video_path: str,
    content_type: str,
    db: Session
):
    """Background task for processing video"""

    async def status_callback(update: dict):
        """Update job status"""
        processing_jobs[job_id].update(update)

    try:
        # Process video to HLS
        result = await video_task_service.process_video_to_hls(
            video_id=content_id,
            input_video_path=video_path,
            content_type=content_type,
            callback=status_callback
        )

        # Update database with HLS URL
        if result['status'] == VideoProcessingStatus.COMPLETED:
            if content_type == 'movie':
                movie = db.query(Movie).filter(Movie.id == content_id).first()
                if movie:
                    movie.video_url = result['hls_url']
                    movie.duration = int(result['duration'])
                    db.commit()
            else:
                episode = db.query(Episode).filter(Episode.id == content_id).first()
                if episode:
                    episode.video_url = result['hls_url']
                    episode.duration = int(result['duration'])
                    db.commit()

            logger.info(f"✅ Database updated with HLS URL for {content_type} {content_id}")

    except Exception as e:
        logger.error(f"❌ Background processing failed: {e}")
        processing_jobs[job_id] = {
            'status': VideoProcessingStatus.FAILED,
            'progress': 0,
            'message': str(e),
            'content_type': content_type,
            'content_id': content_id
        }

    finally:
        # Cleanup temp video
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass


async def process_existing_video_background(
    job_id: str,
    content_id: int,
    video_url: str,
    content_type: str,
    db: Session
):
    """Background task for converting existing video"""

    async def status_callback(update: dict):
        """Update job status"""
        processing_jobs[job_id].update(update)

    try:
        # Process video from URL
        result = await video_task_service.process_video_from_url(
            video_id=content_id,
            video_url=video_url,
            content_type=content_type,
            callback=status_callback
        )

        # Update database with HLS URL
        if result['status'] == VideoProcessingStatus.COMPLETED:
            if content_type == 'movie':
                movie = db.query(Movie).filter(Movie.id == content_id).first()
                if movie:
                    movie.video_url = result['hls_url']
                    movie.duration = int(result['duration'])
                    db.commit()
            else:
                episode = db.query(Episode).filter(Episode.id == content_id).first()
                if episode:
                    episode.video_url = result['hls_url']
                    episode.duration = int(result['duration'])
                    db.commit()

    except Exception as e:
        logger.error(f"❌ Background processing failed: {e}")
        processing_jobs[job_id] = {
            'status': VideoProcessingStatus.FAILED,
            'progress': 0,
            'message': str(e),
            'content_type': content_type,
            'content_id': content_id
        }
