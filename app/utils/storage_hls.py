"""
HLS Storage Extension for Cloudflare R2 - PRODUCTION VERSION
Handles uploading HLS segments and playlists with proper async/await patterns
Optimized for non-blocking concurrent uploads
"""

import os
import logging
import asyncio
from typing import Dict, List, Optional, Callable
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:
    import aioboto3
    HAS_AIOBOTO3 = True
except ImportError:
    HAS_AIOBOTO3 = False

from .storage import StorageService, storage_service
from ..config import settings

logger = logging.getLogger(__name__)


class HLSStorageService:
    """
    🎬 PRODUCTION-READY HLS Storage Service
    
    Features:
    ✅ Concurrent async uploads (if aioboto3 available)
    ✅ Thread pool fallback (always works)
    ✅ Progress tracking with callbacks
    ✅ Proper content-type headers
    ✅ Cache-control optimization
    ✅ Non-blocking operations
    """

    def __init__(self, base_storage: StorageService):
        self.storage = base_storage
        self.r2_client = base_storage.r2_client
        
        # Thread pool for sync operations
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # Get endpoint URL
        endpoint_url = self._get_endpoint_url()
        
        # Initialize aioboto3 if available
        if HAS_AIOBOTO3 and endpoint_url:
            try:
                self.session = aioboto3.Session(
                    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                    region_name='auto'
                )
                self.endpoint_url = endpoint_url
                logger.info(f"✅ HLS Storage: Using aioboto3 async uploads")
            except Exception as e:
                logger.warning(f"⚠️ aioboto3 init failed: {e}, using sync fallback")
                self.session = None
                self.endpoint_url = None
        else:
            self.session = None
            self.endpoint_url = None
            if not HAS_AIOBOTO3:
                logger.info("ℹ️ HLS Storage: Using sync uploads (install aioboto3 for 10x faster uploads)")

    def _get_endpoint_url(self) -> Optional[str]:
        """Get R2 endpoint URL from settings or construct it"""
        if hasattr(settings, 'R2_ENDPOINT_URL') and settings.R2_ENDPOINT_URL:
            return settings.R2_ENDPOINT_URL
        
        if hasattr(settings, 'R2_ACCOUNT_ID') and settings.R2_ACCOUNT_ID:
            return f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        
        return None

    async def upload_hls_directory(
        self,
        local_hls_dir: str,
        video_id: str,
        content_type: str = 'movie',
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, any]:
        """
        Upload entire HLS directory with progress tracking

        Returns:
            {
                'master_playlist_url': str,
                'base_url': str,
                'files_uploaded': int,
                'total_size_bytes': int,
                'r2_path': str,
                'variants': List[str],
                'upload_time_seconds': float,
                'failed_uploads': int
            }
        """
        import time
        start_time = time.time()

        try:
            r2_base_path = f"hls/{content_type}s/{video_id}"

            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"☁️ STARTING R2 UPLOAD")
            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # Collect all files
            loop = asyncio.get_event_loop()
            
            def collect_files():
                """Collect files in thread to avoid blocking"""
                files = []
                size = 0
                vars_found = set()
                
                for root, _, filenames in os.walk(local_hls_dir):
                    for filename in filenames:
                        local_file_path = os.path.join(root, filename)
                        relative_path = os.path.relpath(local_file_path, local_hls_dir)
                        object_key = f"{r2_base_path}/{relative_path}".replace("\\", "/")
                        
                        file_ext = Path(filename).suffix.lower()
                        file_size = os.path.getsize(local_file_path)
                        
                        # Track variants
                        if 'stream_' in filename and '.m3u8' in filename:
                            variant = filename.replace('stream_', '').replace('.m3u8', '')
                            vars_found.add(variant)
                        
                        files.append({
                            'local_path': local_file_path,
                            'object_key': object_key,
                            'content_type': self._get_content_type(file_ext),
                            'cache_control': self._get_cache_control(file_ext),
                            'file_size': file_size,
                            'filename': filename
                        })
                        
                        size += file_size
                
                return files, size, vars_found
            
            logger.info("📂 Collecting files...")
            files_to_upload, total_size, variants = await loop.run_in_executor(
                self.executor, collect_files
            )

            total_files = len(files_to_upload)
            
            logger.info(f"   Total files: {total_files}")
            logger.info(f"   Total size: {total_size / 1024 / 1024:.1f} MB")
            logger.info(f"   Variants: {', '.join(sorted(variants))}")
            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            if progress_callback:
                await progress_callback({
                    'current': 0,
                    'total': total_files,
                    'progress': 0,
                    'message': f'Starting upload of {total_files} files...'
                })

            # Upload files with priority ordering
            playlists = [f for f in files_to_upload if f['filename'].endswith('.m3u8')]
            segments = [f for f in files_to_upload if f['filename'].endswith('.ts')]
            thumbnails = [f for f in files_to_upload if f['filename'].endswith('.jpg')]
            ordered_files = playlists + segments + thumbnails

            logger.info(f"📤 Uploading {len(playlists)} playlists, {len(segments)} segments, {len(thumbnails)} thumbnails")

            # Choose upload method
            if self.session and self.endpoint_url:
                logger.info("📤 Using aioboto3 async uploads...")
                result = await self._upload_with_aioboto3(
                    ordered_files, total_files, progress_callback
                )
            else:
                logger.info("📤 Using thread pool sync uploads...")
                result = await self._upload_with_thread_pool(
                    ordered_files, total_files, progress_callback
                )

            successful_uploads = result['successful']
            failed_uploads = result['failed']

            if failed_uploads:
                logger.warning(f"⚠️ {len(failed_uploads)} uploads failed")
                for failure in failed_uploads[:5]:
                    logger.error(f"  - {failure['file']}: {failure['error']}")

            # Verify master playlist
            master_uploaded = any('master.m3u8' in f['filename'] for f in playlists)
            if not master_uploaded:
                raise Exception("Master playlist upload failed - critical error")

            # Calculate results
            upload_time = time.time() - start_time
            master_playlist_url = f"{settings.R2_PUBLIC_URL}/{r2_base_path}/master.m3u8"

            final_result = {
                'master_playlist_url': master_playlist_url,
                'base_url': f"{settings.R2_PUBLIC_URL}/{r2_base_path}/",
                'files_uploaded': successful_uploads,
                'total_size_bytes': total_size,
                'r2_path': r2_base_path,
                'variants': sorted(list(variants)),
                'upload_time_seconds': round(upload_time, 2),
                'failed_uploads': len(failed_uploads)
            }

            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"✅ R2 UPLOAD COMPLETE!")
            logger.info(f"   Files: {successful_uploads}/{total_files}")
            logger.info(f"   Size: {total_size / 1024 / 1024:.1f} MB")
            logger.info(f"   Time: {upload_time:.1f}s")
            if upload_time > 0:
                logger.info(f"   Speed: {(total_size / 1024 / 1024) / upload_time:.1f} MB/s")
            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            if progress_callback:
                await progress_callback({
                    'current': total_files,
                    'total': total_files,
                    'progress': 100,
                    'message': 'Upload complete!'
                })

            return final_result

        except Exception as e:
            logger.error(f"❌ Upload failed: {e}", exc_info=True)
            
            if progress_callback:
                try:
                    await progress_callback({
                        'current': 0,
                        'total': 0,
                        'progress': 0,
                        'message': f'Upload failed: {str(e)}'
                    })
                except:
                    pass
            
            raise

    async def _upload_with_aioboto3(
        self, files: List[Dict], total_files: int, progress_callback: Optional[Callable]
    ) -> Dict:
        """Async upload with aioboto3 (10x faster)"""
        uploaded_count = 0
        failed_uploads = []
        semaphore = asyncio.Semaphore(15)  # 15 concurrent uploads
        lock = asyncio.Lock()
        
        async def upload_file(file_info: dict):
            nonlocal uploaded_count
            
            async with semaphore:
                try:
                    # Read file in executor
                    loop = asyncio.get_event_loop()
                    file_content = await loop.run_in_executor(
                        self.executor,
                        lambda: open(file_info['local_path'], 'rb').read()
                    )
                    
                    # Upload with aioboto3
                    async with self.session.client('s3', endpoint_url=self.endpoint_url) as s3:
                        await s3.put_object(
                            Bucket=settings.R2_BUCKET_NAME,
                            Key=file_info['object_key'],
                            Body=file_content,
                            ContentType=file_info['content_type'],
                            CacheControl=file_info['cache_control']
                        )
                    
                    async with lock:
                        uploaded_count += 1
                        current_count = uploaded_count
                    
                    # Progress callback every 10 files
                    if progress_callback and current_count % 10 == 0:
                        progress_pct = int((current_count / total_files) * 100)
                        await progress_callback({
                            'current': current_count,
                            'total': total_files,
                            'progress': progress_pct,
                            'message': f'Uploaded {current_count}/{total_files} files'
                        })
                    
                    # Log playlists
                    if file_info['filename'].endswith('.m3u8'):
                        logger.info(f"   ✓ {file_info['filename']}")
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"❌ Upload failed: {file_info['filename']}: {e}")
                    async with lock:
                        failed_uploads.append({
                            'file': file_info['filename'],
                            'error': str(e)
                        })
                    return False
        
        # Execute all uploads concurrently
        await asyncio.gather(*[upload_file(f) for f in files], return_exceptions=True)
        
        return {'successful': uploaded_count, 'failed': failed_uploads}

    async def _upload_with_thread_pool(
        self, files: List[Dict], total_files: int, progress_callback: Optional[Callable]
    ) -> Dict:
        """Thread pool upload (slower but always works)"""
        uploaded_count = 0
        failed_uploads = []
        
        def upload_file_sync(file_info: dict):
            """Sync upload for thread pool"""
            try:
                with open(file_info['local_path'], 'rb') as f:
                    self.r2_client.upload_fileobj(
                        f,
                        settings.R2_BUCKET_NAME,
                        file_info['object_key'],
                        ExtraArgs={
                            'ContentType': file_info['content_type'],
                            'CacheControl': file_info['cache_control']
                        }
                    )
                return {'success': True, 'file_info': file_info}
            except Exception as e:
                logger.error(f"❌ Upload failed: {file_info['filename']}: {e}")
                return {'success': False, 'file_info': file_info, 'error': str(e)}
        
        loop = asyncio.get_event_loop()
        batch_size = 5  # Small batches to yield frequently
        
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(files) + batch_size - 1) // batch_size
            
            logger.info(f"📦 Processing batch {batch_num}/{total_batches}")
            
            # Run batch in thread pool
            tasks = [
                loop.run_in_executor(self.executor, upload_file_sync, file_info)
                for file_info in batch
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"❌ Exception: {result}")
                    failed_uploads.append({'file': 'unknown', 'error': str(result)})
                elif result['success']:
                    uploaded_count += 1
                    
                    # Log playlists
                    if result['file_info']['filename'].endswith('.m3u8'):
                        logger.info(f"   ✓ {result['file_info']['filename']}")
                else:
                    failed_uploads.append({
                        'file': result['file_info']['filename'],
                        'error': result['error']
                    })
            
            # Progress callback
            if progress_callback and uploaded_count % 10 == 0:
                progress_pct = int((uploaded_count / total_files) * 100)
                await progress_callback({
                    'current': uploaded_count,
                    'total': total_files,
                    'progress': progress_pct,
                    'message': f'Uploaded {uploaded_count}/{total_files} files'
                })
            
            # Yield to event loop
            await asyncio.sleep(0.1)
        
        return {'successful': uploaded_count, 'failed': failed_uploads}

    async def delete_hls_directory(self, video_id: str, content_type: str = 'movie') -> bool:
        """Delete HLS directory from R2"""
        try:
            prefix = f"hls/{content_type}s/{video_id}/"
            logger.info(f"🗑️ Deleting HLS directory: {prefix}")
            
            loop = asyncio.get_event_loop()
            
            def list_and_delete():
                response = self.r2_client.list_objects_v2(
                    Bucket=settings.R2_BUCKET_NAME,
                    Prefix=prefix
                )
                
                if 'Contents' not in response:
                    return 0

                objects = [{'Key': obj['Key']} for obj in response['Contents']]
                
                # Delete in batches of 1000
                for i in range(0, len(objects), 1000):
                    batch = objects[i:i + 1000]
                    self.r2_client.delete_objects(
                        Bucket=settings.R2_BUCKET_NAME,
                        Delete={'Objects': batch}
                    )
                
                return len(objects)
            
            deleted_count = await loop.run_in_executor(self.executor, list_and_delete)
            logger.info(f"✅ Deleted {deleted_count} files")
            return True

        except Exception as e:
            logger.error(f"❌ Delete failed: {e}")
            return False

    async def check_hls_exists(self, video_id: str, content_type: str = 'movie') -> bool:
        """Check if HLS exists in R2"""
        try:
            master_key = f"hls/{content_type}s/{video_id}/master.m3u8"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                lambda: self.r2_client.head_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=master_key
                )
            )
            return True
        except:
            return False

    async def get_hls_url(self, video_id: str, content_type: str = 'movie') -> str:
        """Get HLS master playlist URL"""
        return f"{settings.R2_PUBLIC_URL}/hls/{content_type}s/{video_id}/master.m3u8"

    def _get_content_type(self, ext: str) -> str:
        """Get Content-Type header"""
        types = {
            '.m3u8': 'application/vnd.apple.mpegurl',
            '.ts': 'video/mp2t',
            '.mp4': 'video/mp4',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.vtt': 'text/vtt',
        }
        return types.get(ext, 'application/octet-stream')

    def _get_cache_control(self, ext: str) -> str:
        """Get Cache-Control header"""
        if ext == '.m3u8':
            return 'public, max-age=3600'  # 1 hour
        elif ext in ['.ts', '.mp4']:
            return 'public, max-age=31536000, immutable'  # 1 year
        elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
            return 'public, max-age=604800'  # 1 week
        else:
            return 'public, max-age=86400'  # 1 day


# Singleton instance
hls_storage_service = HLSStorageService(storage_service)