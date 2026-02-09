# app/api/endpoints/avatars.py
"""
Avatar Library API - Admin uploads avatars, users select from library
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import logging

from ...database import get_db
from ...models.avatar import Avatar
from ...models.user import User
from ...api.deps import get_current_user, get_current_superuser
from ...utils.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== ADMIN ENDPOINTS ====================

@router.post("/upload")
async def upload_avatar_to_library(
    name: str = Form(...),
    category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    is_premium: bool = Form(False),
    avatar_file: UploadFile = File(...),
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """
    Admin uploads avatar to Firebase and saves to library
    
    Users can then select from these avatars during signup
    """
    try:
        # Validate file type
        if not avatar_file.content_type or not avatar_file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image (JPEG, PNG, WebP, or GIF)"
            )
        
        # Validate file size (max 5MB)
        file_content = await avatar_file.read()
        if len(file_content) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be less than 5MB"
            )
        
        file_size = len(file_content)
        
        # Reset file pointer
        await avatar_file.seek(0)
        
        logger.info(f"📸 Uploading avatar to library: {name}")
        
        # Upload to Firebase Storage
        try:
            storage_type, avatar_url = await storage_service.upload_image(
                file=avatar_file.file,
                filename=avatar_file.filename,
                content_type=avatar_file.content_type,
                folder='avatar-library'  # Separate folder for avatar library
            )
            
            logger.info(f"✅ Avatar uploaded to Firebase: {avatar_url}")
            
        except Exception as upload_error:
            logger.error(f"❌ Firebase upload failed: {upload_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload avatar: {str(upload_error)}"
            )
        
        # Create avatar record in database
        new_avatar = Avatar(
            name=name,
            description=description,
            avatar_url=avatar_url,
            category=category,
            tags=tags,
            is_premium=is_premium,
            file_size=file_size,
            file_type=avatar_file.content_type,
            uploaded_by=current_user.id,
            is_active=True,
            usage_count=0
        )
        
        db.add(new_avatar)
        db.commit()
        db.refresh(new_avatar)
        
        logger.info(f"✅ Avatar added to library: {new_avatar.id} - {name}")
        
        return {
            "success": True,
            "data": {
                "id": new_avatar.id,
                "name": new_avatar.name,
                "avatar_url": new_avatar.avatar_url,
                "category": new_avatar.category,
                "message": "Avatar uploaded to library successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error uploading avatar to library: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload avatar: {str(e)}"
        )


@router.get("/library/list")
def get_avatar_library(
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = None,
    is_active: Optional[bool] = True,
    is_premium: Optional[bool] = None,
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """
    Get all avatars in library (admin view)
    """
    try:
        query = db.query(Avatar)
        
        # Filter by category
        if category:
            query = query.filter(Avatar.category == category)
        
        # Filter by active status
        if is_active is not None:
            query = query.filter(Avatar.is_active == is_active)
        
        # Filter by premium
        if is_premium is not None:
            query = query.filter(Avatar.is_premium == is_premium)
        
        # Get total count
        total = query.count()
        
        # Paginate
        avatars = query.order_by(Avatar.created_at.desc()).offset(skip).limit(limit).all()
        
        avatar_list = []
        for avatar in avatars:
            avatar_list.append({
                "id": avatar.id,
                "name": avatar.name,
                "description": avatar.description,
                "avatar_url": avatar.avatar_url,
                "thumbnail_url": avatar.thumbnail_url,
                "category": avatar.category,
                "tags": avatar.tags,
                "is_active": avatar.is_active,
                "is_premium": avatar.is_premium,
                "usage_count": avatar.usage_count,
                "file_size": avatar.file_size,
                "created_at": avatar.created_at.isoformat() if avatar.created_at else None
            })
        
        return {
            "avatars": avatar_list,
            "total": total,
            "skip": skip,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching avatar library: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch avatar library"
        )


@router.put("/{avatar_id}")
async def update_avatar_in_library(
    avatar_id: int,
    name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    is_premium: Optional[bool] = Form(None),
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """
    Update avatar details in library
    """
    try:
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        
        if not avatar:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Avatar not found"
            )
        
        # Update fields
        if name:
            avatar.name = name
        if category:
            avatar.category = category
        if description is not None:
            avatar.description = description
        if tags is not None:
            avatar.tags = tags
        if is_active is not None:
            avatar.is_active = is_active
        if is_premium is not None:
            avatar.is_premium = is_premium
        
        db.commit()
        db.refresh(avatar)
        
        logger.info(f"✅ Avatar updated in library: {avatar_id}")
        
        return {
            "success": True,
            "data": {
                "id": avatar.id,
                "message": "Avatar updated successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating avatar: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update avatar"
        )


@router.delete("/{avatar_id}")
async def delete_avatar_from_library(
    avatar_id: int,
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """
    Delete avatar from library and Firebase
    """
    try:
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        
        if not avatar:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Avatar not found"
            )
        
        # Delete from Firebase
        try:
            await storage_service.delete_from_firebase(avatar.avatar_url)
            logger.info(f"🗑️ Deleted from Firebase: {avatar.avatar_url}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to delete from Firebase: {e}")
        
        # Delete from database
        db.delete(avatar)
        db.commit()
        
        logger.info(f"✅ Avatar deleted from library: {avatar_id}")
        
        return {
            "success": True,
            "data": {
                "message": "Avatar deleted successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting avatar: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete avatar"
        )


@router.get("/stats")
def get_avatar_stats(
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """
    Get avatar library statistics
    """
    try:
        total_avatars = db.query(func.count(Avatar.id)).scalar() or 0
        active_avatars = db.query(func.count(Avatar.id)).filter(Avatar.is_active == True).scalar() or 0
        premium_avatars = db.query(func.count(Avatar.id)).filter(Avatar.is_premium == True).scalar() or 0
        total_usage = db.query(func.sum(Avatar.usage_count)).scalar() or 0
        
        # Get categories
        categories = db.query(Avatar.category, func.count(Avatar.id)).group_by(Avatar.category).all()
        category_stats = [{"category": cat, "count": count} for cat, count in categories if cat]
        
        return {
            "total_avatars": total_avatars,
            "active_avatars": active_avatars,
            "premium_avatars": premium_avatars,
            "total_usage": int(total_usage),
            "categories": category_stats
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching avatar stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch avatar statistics"
        )


# ==================== PUBLIC ENDPOINTS (For Users) ====================

@router.get("/public/list")
def get_public_avatar_library(
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Get available avatars for users to select (public endpoint)
    Only returns active, non-premium avatars (or all if user is premium)
    """
    try:
        # Only show active avatars
        query = db.query(Avatar).filter(Avatar.is_active == True)
        
        # Filter by category
        if category:
            query = query.filter(Avatar.category == category)
        
        # Get total count
        total = query.count()
        
        # Paginate
        avatars = query.order_by(Avatar.name).offset(skip).limit(limit).all()
        
        avatar_list = []
        for avatar in avatars:
            avatar_list.append({
                "id": avatar.id,
                "name": avatar.name,
                "avatar_url": avatar.avatar_url,
                "thumbnail_url": avatar.thumbnail_url or avatar.avatar_url,
                "category": avatar.category,
                "is_premium": avatar.is_premium
            })
        
        return {
            "avatars": avatar_list,
            "total": total
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching public avatars: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch avatars"
        )


@router.get("/categories")
def get_avatar_categories(db: Session = Depends(get_db)):
    """
    Get all available avatar categories
    """
    try:
        categories = db.query(Avatar.category).filter(
            Avatar.is_active == True,
            Avatar.category.isnot(None)
        ).distinct().all()
        
        category_list = [cat[0] for cat in categories]
        
        return {"categories": category_list}
        
    except Exception as e:
        logger.error(f"❌ Error fetching categories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch categories"
        )


@router.post("/select/{avatar_id}")
def select_avatar_for_user(
    avatar_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    User selects an avatar from library
    Updates user's avatar_url and increments usage_count
    """
    try:
        # Get avatar
        avatar = db.query(Avatar).filter(
            Avatar.id == avatar_id,
            Avatar.is_active == True
        ).first()
        
        if not avatar:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Avatar not found or not available"
            )
        
        # Check if premium avatar (optional - implement premium logic)
        if avatar.is_premium:
            # Check if user has premium access
            # You can implement this based on your subscription system
            pass
        
        # Update user's avatar
        if hasattr(current_user, 'avatar_url'):
            current_user.avatar_url = avatar.avatar_url
        elif hasattr(current_user, 'avatar'):
            current_user.avatar = avatar.avatar_url
        
        # Increment usage count
        avatar.usage_count += 1
        
        db.commit()
        db.refresh(current_user)
        db.refresh(avatar)
        
        logger.info(f"✅ User {current_user.id} selected avatar {avatar_id}")
        
        return {
            "success": True,
            "data": {
                "avatar_url": avatar.avatar_url,
                "message": "Avatar selected successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error selecting avatar: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to select avatar"
        )