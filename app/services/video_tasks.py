"""
Video Processing Tasks - PRODUCTION VERSION
Background task handler for video transcoding and HLS conversion
Integrates video_processor + hls_storage seamlessly
"""

import os
import tempfile
import shutil
import logging
from typing import Dict, Optional, Callable
from datetime import datetime
import asyncio

from .video_processor import video_processor
from ..utils.storage_hls import hls_storage_service
from ..config import settings

logger = logging.getLogger(__name__)


class VideoProcessingStatus:
    """Track video processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoProcessingTask:
    """
    🎬 PRODUCTION-READY Video Processing Pipeline
    
    Complete workflow:
    1. Transcode video to HLS (multiple qualities)
    2. Upload all files to R2 storage
    3. Update database with URLs
    4. Clean up temporary files
    5. Send progress updates throughout
    """

    def __init__(self):
        self.processor = video_processor
        self.hls_storage = hls_storage_service
        self.active_jobs = {}  # Track active processing jobs

    async def process_video_to_hls(
        self,
        video_id: int,
        input_video_path: str,
        content_type: str = 'movie',
        callback: Optional[Callable] = None
    ) -> Dict:
        """
        🎬 Complete video processing pipeline with progress tracking

        Args:
            video_id: Unique identifier (movie_id or episode_id)
            input_video_path: Path to original MP4 file
            content_type: 'movie' or 'episode'
            callback: Optional async callback for status updates

        Returns:
            {
                'status': 'completed',
                'video_id': 12345,
                'hls_url': 'https://media.zentrya.africa/hls/movies/12345/master.m3u8',
                'duration': 7200.5,
                'variants': ['240p', '360p', '480p', '720p', '1080p'],
                'processing_time': 300.5
            }
        """
        start_time = datetime.now()
        temp_dir = None

        try:
            # ═══════════════════════════════════════════════════════════
            # PHASE 1: INITIALIZATION (0-5%)
            # ═══════════════════════════════════════════════════════════
            if callback:
                await callback({
                    'status': VideoProcessingStatus.PROCESSING,
                    'progress': 0,
                    'message': 'Initializing video processing...'
                })

            # Verify input file exists
            if not os.path.exists(input_video_path):
                raise FileNotFoundError(f"Video file not found: {input_video_path}")

            file_size_mb = os.path.getsize(input_video_path) / 1024 / 1024
            logger.info(
                f"🎬 Processing video {video_id} ({content_type}) - "
                f"{file_size_mb:.1f} MB"
            )

            # Create temporary directory for HLS output
            temp_dir = tempfile.mkdtemp(prefix=f"hls_{video_id}_")
            logger.info(f"📁 Temp directory: {temp_dir}")

            if callback:
                await callback({
                    'status': VideoProcessingStatus.PROCESSING,
                    'progress': 5,
                    'message': f'Processing {file_size_mb:.1f} MB video...'
                })

            # ═══════════════════════════════════════════════════════════
            # PHASE 2: HLS TRANSCODING (5-75%)
            # ═══════════════════════════════════════════════════════════
            
            logger.info("🔄 Starting HLS transcoding...")
            
            async def transcode_progress(update: dict):
                """Forward transcoding progress to main callback"""
                if callback:
                    # Transcoding is 5-75% of total progress
                    transcode_progress = update.get('progress', 0)
                    total_progress = 5 + int(transcode_progress * 0.7)
                    
                    await callback({
                        'status': VideoProcessingStatus.PROCESSING,
                        'progress': total_progress,
                        'message': update.get('message', 'Transcoding...')
                    })

            hls_result = await self.processor.transcode_to_hls(
                input_video_path,
                temp_dir,
                progress_callback=transcode_progress
            )

            logger.info(
                f"✅ Transcoding complete: {len(hls_result['variants'])} variants, "
                f"{hls_result['duration']:.1f}s duration"
            )

            # ═══════════════════════════════════════════════════════════
            # PHASE 3: UPLOAD TO R2 (75-95%)
            # ═══════════════════════════════════════════════════════════
            
            logger.info("☁️ Uploading HLS files to R2...")
            
            if callback:
                await callback({
                    'status': VideoProcessingStatus.PROCESSING,
                    'progress': 75,
                    'message': 'Uploading to cloud storage...'
                })

            async def upload_progress(update: dict):
                """Forward upload progress to main callback"""
                if callback:
                    # Upload is 75-95% of total progress
                    upload_pct = update.get('progress', 0)
                    total_progress = 75 + int(upload_pct * 0.2)
                    
                    await callback({
                        'status': VideoProcessingStatus.PROCESSING,
                        'progress': total_progress,
                        'message': update.get('message', 'Uploading...')
                    })

            upload_result = await self.hls_storage.upload_hls_directory(
                temp_dir,
                str(video_id),
                content_type,
                progress_callback=upload_progress
            )

            logger.info(
                f"✅ Upload complete: {upload_result['files_uploaded']} files, "
                f"{upload_result['total_size_bytes'] / 1024 / 1024:.1f} MB in "
                f"{upload_result['upload_time_seconds']:.1f}s"
            )

            # ═══════════════════════════════════════════════════════════
            # PHASE 4: CLEANUP (95-100%)
            # ═══════════════════════════════════════════════════════════
            
            if callback:
                await callback({
                    'status': VideoProcessingStatus.PROCESSING,
                    'progress': 95,
                    'message': 'Cleaning up temporary files...'
                })

            logger.info("🗑️ Cleaning up temporary files...")
            await self.processor.cleanup_temp_files(temp_dir)
            temp_dir = None

            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds()

            # ═══════════════════════════════════════════════════════════
            # PHASE 5: FINAL RESULT (100%)
            # ═══════════════════════════════════════════════════════════
            
            result = {
                'status': VideoProcessingStatus.COMPLETED,
                'video_id': video_id,
                'hls_url': upload_result['master_playlist_url'],
                'base_url': upload_result['base_url'],
                'duration': hls_result['duration'],
                'variants': upload_result['variants'],
                'thumbnails': hls_result['thumbnails'],
                'files_uploaded': upload_result['files_uploaded'],
                'total_size_bytes': upload_result['total_size_bytes'],
                'processing_time_seconds': round(processing_time, 2),
                'source_info': hls_result['source_info'],
                'audio_only': hls_result.get('audio_only') is not None
            }

            if callback:
                await callback({
                    'status': VideoProcessingStatus.COMPLETED,
                    'progress': 100,
                    'message': 'Processing complete!',
                    'result': result
                })

            logger.info(
                f"🎉 Video processing complete! "
                f"{video_id} -> {upload_result['master_playlist_url']} "
                f"({processing_time:.1f}s total)"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Video processing failed: {e}", exc_info=True)

            # Cleanup on error
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"🗑️ Cleaned up temp dir after error: {temp_dir}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup temp dir: {cleanup_error}")

            if callback:
                await callback({
                    'status': VideoProcessingStatus.FAILED,
                    'progress': 0,
                    'message': f'Processing failed: {str(e)}'
                })

            return {
                'status': VideoProcessingStatus.FAILED,
                'video_id': video_id,
                'error': str(e)
            }

    async def delete_hls_video(
        self,
        video_id: int,
        content_type: str = 'movie'
    ) -> bool:
        """
        Delete HLS video from R2 storage

        Args:
            video_id: Unique identifier
            content_type: 'movie' or 'episode'

        Returns:
            True if deletion successful, False otherwise
        """
        try:
            logger.info(f"🗑️ Deleting HLS video: {video_id} ({content_type})")
            
            success = await self.hls_storage.delete_hls_directory(
                str(video_id),
                content_type
            )
            
            if success:
                logger.info(f"✅ HLS video deleted: {video_id}")
            else:
                logger.warning(f"⚠️ HLS video deletion failed or not found: {video_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Failed to delete HLS video: {e}")
            return False

    async def check_hls_exists(
        self,
        video_id: int,
        content_type: str = 'movie'
    ) -> bool:
        """Check if HLS video exists in R2"""
        return await self.hls_storage.check_hls_exists(str(video_id), content_type)

    def get_hls_url(self, video_id: int, content_type: str = 'movie') -> str:
        """Get HLS master playlist URL"""
        return f"{settings.R2_PUBLIC_URL}/hls/{content_type}s/{video_id}/master.m3u8"


# ═══════════════════════════════════════════════════════════════════════
# Singleton instance
# ═══════════════════════════════════════════════════════════════════════
video_task_service = VideoProcessingTask()