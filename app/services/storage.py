import os
import shutil
import boto3
from typing import Optional, BinaryIO
from fastapi import UploadFile, HTTPException
from ..config import settings
import magic
from PIL import Image
import io

class StorageService:
    def __init__(self):
        self.storage_type = settings.STORAGE_TYPE
        if self.storage_type == "s3":
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
        else:
            # Ensure upload directory exists for local storage
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    async def upload_file(
        self, 
        file: UploadFile, 
        folder: str = "media",
        allowed_types: list = None
    ) -> str:
        """Upload file to storage and return URL"""
        
        # Validate file size
        content = await file.read()
        if len(content) > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max size: {settings.MAX_FILE_SIZE} bytes"
            )
        
        # Validate file type
        file_type = magic.from_buffer(content, mime=True)
        if allowed_types and file_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {allowed_types}"
            )
        
        # Generate unique filename
        filename = f"{folder}/{file.filename}"
        
        if self.storage_type == "s3":
            return await self._upload_to_s3(content, filename, file_type)
        else:
            return await self._upload_to_local(content, filename)

    async def _upload_to_s3(self, content: bytes, filename: str, content_type: str) -> str:
        """Upload file to S3"""
        try:
            self.s3_client.put_object(
                Bucket=settings.AWS_S3_BUCKET,
                Key=filename,
                Body=content,
                ContentType=content_type
            )
            return f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")

    async def _upload_to_local(self, content: bytes, filename: str) -> str:
        """Upload file to local storage"""
        file_path = os.path.join(settings.UPLOAD_DIR, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        return f"/uploads/{filename}"

    async def delete_file(self, file_url: str) -> bool:
        """Delete file from storage"""
        if self.storage_type == "s3":
            return await self._delete_from_s3(file_url)
        else:
            return await self._delete_from_local(file_url)

    async def _delete_from_s3(self, file_url: str) -> bool:
        """Delete file from S3"""
        try:
            # Extract key from URL
            key = file_url.split(f"{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/")[1]
            self.s3_client.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
            return True
        except Exception:
            return False

    async def _delete_from_local(self, file_url: str) -> bool:
        """Delete file from local storage"""
        try:
            # Extract path from URL
            file_path = os.path.join(settings.UPLOAD_DIR, file_url.replace("/uploads/", ""))
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception:
            return False

    def resize_image(self, content: bytes, max_width: int = 1920, max_height: int = 1080) -> bytes:
        """Resize image while maintaining aspect ratio"""
        try:
            image = Image.open(io.BytesIO(content))
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            output = io.BytesIO()
            format = image.format if image.format else 'JPEG'
            image.save(output, format=format, quality=85)
            return output.getvalue()
        except Exception:
            return content

storage_service = StorageService()