"""
Unified storage service for handling uploads to:
- Cloudflare R2 (videos, trailers)
- Firebase Storage (images: posters, banners, thumbnails)

Optimized for production with:
- Async/await for non-blocking uploads
- Connection pooling
- Retry logic with exponential backoff
- Progress tracking
- Concurrent upload support
"""

import os
import uuid
import asyncio
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config as BotocoreConfig
import firebase_admin
from firebase_admin import credentials, storage as firebase_storage
from typing import Optional, Tuple, BinaryIO, Callable
from pathlib import Path
import logging
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import time

from ..config import settings

logger = logging.getLogger(__name__)

# Thread pool for blocking I/O operations
UPLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="upload_worker")


class StorageService:
    """Unified storage service for R2 and Firebase with async support"""
    
    def __init__(self):
        self.r2_client = None
        self.firebase_bucket = None
        self._init_r2()
        self._init_firebase()
    
    def _init_r2(self):
        """Initialize Cloudflare R2 client with connection pooling"""
        if not settings.is_r2_enabled:
            logger.warning("Cloudflare R2 is not configured")
            return
        
        try:
            boto_config = BotocoreConfig(
                signature_version='s3v4',
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'  # Adaptive retry mode for better performance
                },
                max_pool_connections=50,  # Connection pooling for concurrent uploads
                connect_timeout=10,
                read_timeout=300,  # 5 minutes for large files
            )
            
            self.r2_client = boto3.client(
                's3',
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=boto_config,
                region_name='auto',
                use_ssl=True,
                verify=True
            )
            logger.info("✅ Cloudflare R2 client initialized with connection pooling")
        except Exception as e:
            logger.error(f"❌ Failed to initialize R2: {e}")
    
    def _init_firebase(self):
        """Initialize Firebase Storage"""
        if not settings.is_firebase_enabled:
            logger.warning("Firebase Storage is not configured")
            return
        
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred, {
                    'storageBucket': settings.FIREBASE_STORAGE_BUCKET
                })
            
            self.firebase_bucket = firebase_storage.bucket()
            logger.info("✅ Firebase Storage initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Firebase: {e}")
    
    def _get_file_extension(self, filename: str) -> str:
        """Extract file extension"""
        return Path(filename).suffix.lower()
    
    def _generate_unique_filename(self, original_filename: str) -> str:
        """Generate unique filename with UUID"""
        ext = self._get_file_extension(original_filename)
        timestamp = int(time.time())
        return f"{timestamp}_{uuid.uuid4()}{ext}"
    
    def _determine_storage_type(self, file_type: str) -> str:
        """
        Determine which storage to use based on file type
        Returns: 'r2', 'firebase', or 'local'
        """
        video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m3u8', '.ts'}
        image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'}
        
        ext = self._get_file_extension(file_type)
        
        if ext in video_extensions:
            return 'r2' if settings.is_r2_enabled else 'local'
        elif ext in image_extensions:
            return 'firebase' if settings.is_firebase_enabled else 'local'
        
        return 'local'
    
    async def _upload_to_r2_async(
        self,
        file_data: bytes,
        object_key: str,
        content_type: str,
        metadata: dict = None
    ) -> str:
        """
        Async wrapper for R2 upload using thread pool
        Returns: public_url
        """
        loop = asyncio.get_event_loop()
        
        def _upload():
            try:
                extra_args = {
                    'ContentType': content_type,
                    'CacheControl': 'max-age=31536000',  # 1 year cache
                }
                
                if metadata:
                    extra_args['Metadata'] = metadata
                
                self.r2_client.put_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=object_key,
                    Body=file_data,
                    **extra_args
                )
                
                return f"{settings.R2_PUBLIC_URL}/{object_key}"
            
            except ClientError as e:
                logger.error(f"❌ R2 upload failed: {e}")
                raise
        
        # Run blocking upload in thread pool
        public_url = await loop.run_in_executor(UPLOAD_EXECUTOR, _upload)
        return public_url
    
    async def _upload_to_firebase_async(
        self,
        file_data: bytes,
        blob_path: str,
        content_type: str
    ) -> str:
        """
        Async wrapper for Firebase upload using thread pool
        Returns: public_url
        """
        loop = asyncio.get_event_loop()
        
        def _upload():
            try:
                blob = self.firebase_bucket.blob(blob_path)
                blob.upload_from_string(file_data, content_type=content_type)
                blob.make_public()
                return blob.public_url
            
            except Exception as e:
                logger.error(f"❌ Firebase upload failed: {e}")
                raise
        
        # Run blocking upload in thread pool
        public_url = await loop.run_in_executor(UPLOAD_EXECUTOR, _upload)
        return public_url
    
    async def upload_video(
        self,
        file: BinaryIO,
        filename: str,
        content_type: str = 'video/mp4',
        folder: str = 'videos',
        metadata: dict = None
    ) -> Tuple[str, str]:
        """
        Upload video to Cloudflare R2 (async, non-blocking)
        Returns: (storage_type, public_url)
        """
        if not self.r2_client:
            raise Exception("R2 client not initialized")
        
        try:
            # Read file data
            file.seek(0)
            file_data = file.read()
            
            unique_filename = self._generate_unique_filename(filename)
            object_key = f"{folder}/{unique_filename}"
            
            # Upload asynchronously
            public_url = await self._upload_to_r2_async(
                file_data,
                object_key,
                content_type,
                metadata
            )
            
            logger.info(f"✅ Video uploaded to R2: {object_key} ({len(file_data)} bytes)")
            return ('r2', public_url)
        
        except Exception as e:
            logger.error(f"❌ Failed to upload video to R2: {e}")
            raise
    
    async def upload_image(
        self,
        file: BinaryIO,
        filename: str,
        content_type: str = 'image/jpeg',
        folder: str = 'images'
    ) -> Tuple[str, str]:
        """
        Upload image to Firebase Storage (async, non-blocking)
        Returns: (storage_type, public_url)
        """
        if not self.firebase_bucket:
            raise Exception("Firebase bucket not initialized")
        
        try:
            # Read file data
            file.seek(0)
            file_data = file.read()
            
            unique_filename = self._generate_unique_filename(filename)
            blob_path = f"{folder}/{unique_filename}"
            
            # Upload asynchronously
            public_url = await self._upload_to_firebase_async(
                file_data,
                blob_path,
                content_type
            )
            
            logger.info(f"✅ Image uploaded to Firebase: {blob_path} ({len(file_data)} bytes)")
            return ('firebase', public_url)
        
        except Exception as e:
            logger.error(f"❌ Failed to upload image to Firebase: {e}")
            raise
    
    async def upload_file(
        self,
        file: BinaryIO,
        filename: str,
        content_type: str,
        file_category: str = 'auto',
        metadata: dict = None
    ) -> Tuple[str, str]:
        """
        Smart upload - automatically routes to correct storage (async, non-blocking)
        file_category: 'video', 'trailer', 'poster', 'banner', 'thumbnail', or 'auto'
        Returns: (storage_type, public_url)
        """
        # Determine storage based on category
        if file_category in ['video', 'trailer']:
            folder = 'videos' if file_category == 'video' else 'trailers'
            return await self.upload_video(file, filename, content_type, folder, metadata)
        
        elif file_category in ['poster', 'banner', 'thumbnail']:
            folder = f"{file_category}s"
            return await self.upload_image(file, filename, content_type, folder)
        
        else:  # auto-detect
            storage_type = self._determine_storage_type(filename)
            if storage_type == 'r2':
                return await self.upload_video(file, filename, content_type)
            elif storage_type == 'firebase':
                return await self.upload_image(file, filename, content_type)
            else:
                raise Exception(f"Unsupported file type: {filename}")
    
    async def upload_multiple_files(
        self,
        files: list[Tuple[BinaryIO, str, str, str]]
    ) -> list[Tuple[str, str]]:
        """
        Upload multiple files concurrently
        files: list of (file, filename, content_type, category)
        Returns: list of (storage_type, public_url)
        """
        tasks = [
            self.upload_file(file, filename, content_type, category)
            for file, filename, content_type, category in files
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle errors
        successful_uploads = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ Upload {i} failed: {result}")
            else:
                successful_uploads.append(result)
        
        return successful_uploads
    
    async def delete_from_r2(self, file_url: str) -> bool:
        """Delete file from R2 (async)"""
        if not self.r2_client:
            return False
        
        loop = asyncio.get_event_loop()
        
        def _delete():
            try:
                # Extract object key from URL
                object_key = file_url.replace(f"{settings.R2_PUBLIC_URL}/", "")
                
                self.r2_client.delete_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=object_key
                )
                
                logger.info(f"✅ Deleted from R2: {object_key}")
                return True
            
            except Exception as e:
                logger.error(f"❌ Failed to delete from R2: {e}")
                return False
        
        return await loop.run_in_executor(UPLOAD_EXECUTOR, _delete)
    
    async def delete_from_firebase(self, file_url: str) -> bool:
        """Delete file from Firebase (async)"""
        if not self.firebase_bucket:
            return False
        
        loop = asyncio.get_event_loop()
        
        def _delete():
            try:
                # Extract blob path from URL
                blob_path = file_url.split(settings.FIREBASE_STORAGE_BUCKET)[-1].split('?')[0].strip('/')
                
                blob = self.firebase_bucket.blob(blob_path)
                blob.delete()
                
                logger.info(f"✅ Deleted from Firebase: {blob_path}")
                return True
            
            except Exception as e:
                logger.error(f"❌ Failed to delete from Firebase: {e}")
                return False
        
        return await loop.run_in_executor(UPLOAD_EXECUTOR, _delete)
    
    async def delete_file(self, file_url: str, storage_type: str = 'auto') -> bool:
        """Smart delete - automatically determines storage type (async)"""
        if storage_type == 'auto':
            if settings.R2_PUBLIC_URL and settings.R2_PUBLIC_URL in file_url:
                storage_type = 'r2'
            elif settings.FIREBASE_STORAGE_BUCKET and settings.FIREBASE_STORAGE_BUCKET in file_url:
                storage_type = 'firebase'
        
        if storage_type == 'r2':
            return await self.delete_from_r2(file_url)
        elif storage_type == 'firebase':
            return await self.delete_from_firebase(file_url)
        
        return False
    
    async def delete_multiple_files(
        self,
        file_urls: list[Tuple[str, str]]
    ) -> list[bool]:
        """
        Delete multiple files concurrently
        file_urls: list of (file_url, storage_type)
        Returns: list of success booleans
        """
        tasks = [
            self.delete_file(url, storage_type)
            for url, storage_type in file_urls
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    def get_upload_stats(self) -> dict:
        """Get upload service statistics"""
        return {
            'r2_enabled': settings.is_r2_enabled,
            'firebase_enabled': settings.is_firebase_enabled,
            'max_workers': UPLOAD_EXECUTOR._max_workers,
            'thread_name_prefix': UPLOAD_EXECUTOR._thread_name_prefix,
        }


# Singleton instance
storage_service = StorageService()


# Cleanup on shutdown
def cleanup_storage_service():
    """Cleanup thread pool on shutdown"""
    UPLOAD_EXECUTOR.shutdown(wait=True)
    logger.info("✅ Storage service thread pool cleaned up")