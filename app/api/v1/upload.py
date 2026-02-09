# app/api/v1/endpoints/upload.py
"""
File upload endpoints - FIXED for 405 error
"""
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import User
from ...utils.storage import storage_service
from ..deps import get_current_user
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])

# File type validation
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp", "image/gif"}
ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/mpeg", "video/quicktime", 
    "video/x-msvideo", "video/x-matroska", "video/webm"
}

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_VIDEO_SIZE = 5 * 1024 * 1024 * 1024  # 5GB


@router.post("")  # ✅ FIXED: Empty string responds to /api/v1/upload
async def upload_single_file(
    file: UploadFile = File(...),
    type: str = Form(...),  # ✅ Changed back to 'type' to match frontend
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a single file to cloud storage
    
    POST /api/v1/upload
    
    Parameters:
    - file: The file to upload
    - type: One of 'poster', 'banner', 'video', 'trailer', 'thumbnail'
    
    Returns:
    - url: Public URL of the uploaded file
    - storage_type: Where file was stored ('r2' or 'firebase')
    - filename: Original filename
    """
    try:
        # Validate file type parameter
        valid_types = ['poster', 'banner', 'video', 'trailer', 'thumbnail']
        if type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"type must be one of: {', '.join(valid_types)}"
            )
        
        # Determine if it's image or video
        is_video = type in ['video', 'trailer']
        is_image = type in ['poster', 'banner', 'thumbnail']
        
        # Validate file content type
        if is_image and file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}"
            )
        
        if is_video and file.content_type not in ALLOWED_VIDEO_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid video type. Allowed: {', '.join(ALLOWED_VIDEO_TYPES)}"
            )
        
        # Check file size
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if is_image and file_size > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image too large. Max: {MAX_IMAGE_SIZE / (1024*1024):.0f}MB"
            )
        
        if is_video and file_size > MAX_VIDEO_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Video too large. Max: {MAX_VIDEO_SIZE / (1024*1024*1024):.0f}GB"
            )
        
        logger.info(f"📤 Uploading {type}: {file.filename} ({file_size / (1024*1024):.2f}MB) by {current_user.email}")
        
        # Upload to cloud storage
        storage_type, file_url = await storage_service.upload_file(
            file.file,
            file.filename,
            file.content_type,
            file_category=type
        )
        
        logger.info(f"✅ Uploaded to {storage_type.upper()}: {file_url}")
        
        return {
            "url": file_url,
            "filename": file.filename,
            "type": type,
            "storage_type": storage_type,
            "size": file_size,
            "message": f"{type.capitalize()} uploaded successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Upload error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.post("/multiple")
async def upload_multiple_files(
    files: list[UploadFile] = File(...),
    types: str = Form(...),  # JSON string array like '["poster", "banner"]'
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload multiple files at once
    
    POST /api/v1/upload/multiple
    """
    import json
    
    try:
        types_list = json.loads(types)
        
        if len(files) != len(types_list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Files count ({len(files)}) must match types count ({len(types_list)})"
            )
        
        results = []
        success_count = 0
        failed_count = 0
        
        for file, file_type in zip(files, types_list):
            try:
                storage_type, file_url = await storage_service.upload_file(
                    file.file,
                    file.filename,
                    file.content_type,
                    file_category=file_type
                )
                
                results.append({
                    "filename": file.filename,
                    "type": file_type,
                    "url": file_url,
                    "storage_type": storage_type,
                    "success": True
                })
                success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to upload {file.filename}: {e}")
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": str(e)
                })
                failed_count += 1
        
        logger.info(f"Batch upload: {success_count} succeeded, {failed_count} failed")
        
        return {
            "uploads": results,
            "success_count": success_count,
            "failed_count": failed_count,
            "total": len(files),
            "message": f"Uploaded {success_count}/{len(files)} files"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch upload failed: {str(e)}"
        )


@router.delete("")
async def delete_file(
    file_url: str = Form(...),
    storage_type: str = Form("auto"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a file from cloud storage
    
    DELETE /api/v1/upload
    """
    try:
        success = await storage_service.delete_file(file_url, storage_type)
        
        if success:
            logger.info(f"✅ File deleted: {file_url}")
            return {
                "success": True,
                "message": "File deleted successfully"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found or already deleted"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}"
        )


@router.get("/storage-info")
async def get_storage_info(
    current_user: User = Depends(get_current_user)
):
    """Get storage configuration info"""
    from ...config import settings
    
    return {
        "r2_enabled": settings.is_r2_enabled,
        "firebase_enabled": settings.is_firebase_enabled,
        "r2_bucket": settings.R2_BUCKET_NAME if settings.is_r2_enabled else None,
        "r2_public_url": settings.R2_PUBLIC_URL if settings.is_r2_enabled else None,
        "firebase_bucket": settings.FIREBASE_STORAGE_BUCKET if settings.is_firebase_enabled else None,
        "storage_type": settings.STORAGE_TYPE
    }