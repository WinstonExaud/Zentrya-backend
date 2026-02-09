# app/api/endpoints/users.py
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, update, delete
from pydantic import BaseModel, EmailStr
from typing import Literal
from datetime import datetime, timedelta
import logging
import asyncio

from ...database import get_async_db
from ...redis_client import redis_client
from ...models.user import User, UserProfile, UserSettings, UserRole, UserDevice, OtpSession
from ...schemas.user import (
    User as UserSchema, 
    UserCreate, 
    UserUpdate,
    UserProfileCreate,
    UserProfileUpdate
)
from ...api.deps import get_current_superuser, get_current_user
from ...utils.security import verify_password, get_password_hash
from ...utils.otp import generate_otp, send_otp_sms

logger = logging.getLogger(__name__)
router = APIRouter()

# ==================== PYDANTIC MODELS ====================

class UserSettingsUpdate(BaseModel):
    cellular_data_usage: Optional[Literal['automatic', 'wifi_only', 'save_data', 'maximum']] = None
    hdr_playback: Optional[bool] = None
    allow_notifications: Optional[bool] = None
    wifi_only_downloads: Optional[bool] = None
    download_quality: Optional[Literal['low', 'medium', 'standard', 'high']] = None
    download_location: Optional[Literal['internal', 'external']] = None
    autoplay_next: Optional[bool] = None
    autoplay_previews: Optional[bool] = None
    subtitle_preference: Optional[bool] = None
    language_preference: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UpdateEmailRequest(BaseModel):
    new_email: EmailStr
    password: str

class UpdatePhoneRequest(BaseModel):
    new_phone: str
    password: str

class VerifyPhoneRequest(BaseModel):
    otp: str

class MessageResponse(BaseModel):
    message: str

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    language_preference: Optional[str] = None
    subtitle_preference: Optional[bool] = None
    autoplay_next: Optional[bool] = None

class ProfilePinRequest(BaseModel):
    pin: str

class UserStatusUpdate(BaseModel):
    is_active: bool

class BulkUserAction(BaseModel):
    user_ids: List[int]

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    phone: Optional[str]
    role: str
    is_active: bool
    is_superuser: bool
    avatar_url: Optional[str]
    subscription_plan: Optional[str]
    subscription_status: Optional[str]
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True

# ==================== HELPER FUNCTIONS ====================

def parse_user_agent(user_agent: str) -> dict:
    """Parse user agent string to extract device information"""
    device_info = {
        "device_name": "Unknown Device",
        "device_type": "Unknown",
        "browser": None,
        "os": None
    }
    
    if not user_agent:
        return device_info
    
    user_agent_lower = user_agent.lower()
    
    if "mobile" in user_agent_lower or "android" in user_agent_lower or "iphone" in user_agent_lower:
        device_info["device_type"] = "Mobile"
        if "android" in user_agent_lower:
            device_info["device_name"] = "Android Phone"
            device_info["os"] = "Android"
        elif "iphone" in user_agent_lower:
            device_info["device_name"] = "iPhone"
            device_info["os"] = "iOS"
    elif "tablet" in user_agent_lower or "ipad" in user_agent_lower:
        device_info["device_type"] = "Tablet"
        if "ipad" in user_agent_lower:
            device_info["device_name"] = "iPad"
            device_info["os"] = "iOS"
    elif "tv" in user_agent_lower or "smarttv" in user_agent_lower:
        device_info["device_type"] = "TV"
        device_info["device_name"] = "Smart TV"
    else:
        device_info["device_type"] = "Desktop"
        device_info["device_name"] = "Desktop Computer"
        
        if "windows" in user_agent_lower:
            device_info["os"] = "Windows"
        elif "mac" in user_agent_lower:
            device_info["os"] = "macOS"
        elif "linux" in user_agent_lower:
            device_info["os"] = "Linux"
    
    if "chrome" in user_agent_lower and "edg" not in user_agent_lower:
        device_info["browser"] = "Chrome"
    elif "firefox" in user_agent_lower:
        device_info["browser"] = "Firefox"
    elif "safari" in user_agent_lower and "chrome" not in user_agent_lower:
        device_info["browser"] = "Safari"
    elif "edg" in user_agent_lower:
        device_info["browser"] = "Edge"
    
    if device_info["browser"] and device_info["device_type"] == "Mobile":
        device_info["device_name"] = f"{device_info['device_name']} {device_info['browser']}"
    
    return device_info


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Get current authenticated user information"""
    try:
        return {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "phone": getattr(current_user, 'phone', None),
            "role": getattr(current_user, 'role', 'client'),
            "is_active": current_user.is_active,
            "is_superuser": getattr(current_user, 'is_superuser', False),
            "avatar": getattr(current_user, 'avatar', None),
            "subscription_plan": getattr(current_user, 'subscription_plan', None),
            "subscription_status": getattr(current_user, 'subscription_status', None),
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "last_login": current_user.last_login.isoformat() if hasattr(current_user, 'last_login') and current_user.last_login else None,
        }
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user information"
        )

# ==================== USER PROFILE ENDPOINTS (ASYNC + REDIS) ====================

@router.get("/profile/list")
async def get_user_profiles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Get all profiles for the current user (with Redis caching)
    """
    try:
        # Try cache first
        cache_key = f"user:{current_user.id}:profiles"
        cached_profiles = await redis_client.get(cache_key)
        
        if cached_profiles:
            logger.info(f"✅ Cache hit for user {current_user.id} profiles")
            return cached_profiles
        
        # Cache miss - fetch from database (async)
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == current_user.id)
        )
        profiles = result.scalars().all()
        
        # If no profiles exist, create default
        if not profiles:
            default_profile = UserProfile(
                user_id=current_user.id,
                name=getattr(current_user, 'display_name', None) or current_user.full_name or "Main Profile",
                avatar=getattr(current_user, 'avatar_url', None) or "0",
                is_kids=False,
                is_active=True
            )
            db.add(default_profile)
            await db.commit()
            await db.refresh(default_profile)
            profiles = [default_profile]
        
        # Convert to dict
        profile_list = []
        for profile in profiles:
            profile_list.append({
                "id": profile.id,
                "user_id": profile.user_id,
                "name": profile.name,
                "avatar": profile.avatar,
                "is_kids": profile.is_kids,
                "is_active": profile.is_active,
                "language_preference": getattr(profile, 'language_preference', None),
                "subtitle_preference": getattr(profile, 'subtitle_preference', True),
                "autoplay_next": getattr(profile, 'autoplay_next', True),
                "pin_enabled": hasattr(profile, 'pin') and profile.pin is not None,
                "created_at": profile.created_at.isoformat() if hasattr(profile, 'created_at') and profile.created_at else None,
                "updated_at": profile.updated_at.isoformat() if hasattr(profile, 'updated_at') and profile.updated_at else None,
            })
        
        response = {"profiles": profile_list}
        
        # Cache for 5 minutes
        await redis_client.set(cache_key, response, expire=300)
        
        return response
        
    except Exception as e:
        logger.error(f"Error in get_user_profiles: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profile/create")
async def create_profile(
    profile_in: UserProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new profile (async, invalidates cache)"""
    try:
        # Check profile limit (async)
        result = await db.execute(
            select(func.count(UserProfile.id)).where(UserProfile.user_id == current_user.id)
        )
        profile_count = result.scalar()
        
        if profile_count >= 5:
            raise HTTPException(
                status_code=400,
                detail="Maximum 5 profiles allowed per user"
            )
        
        # Create new profile
        new_profile = UserProfile(
            user_id=current_user.id,
            name=profile_in.name,
            avatar=profile_in.avatar,
            is_kids=profile_in.is_kids,
            is_active=False
        )
        
        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)
        
        # Invalidate cache
        cache_key = f"user:{current_user.id}:profiles"
        await redis_client.delete(cache_key)
        
        return {
            "id": new_profile.id,
            "user_id": new_profile.user_id,
            "name": new_profile.name,
            "avatar": new_profile.avatar,
            "is_kids": new_profile.is_kids,
            "is_active": new_profile.is_active,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profile/{profile_id}")
async def update_profile(
    profile_id: int,
    profile_in: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update a profile (async, invalidates cache)"""
    try:
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.user_id == current_user.id
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        # Update fields
        update_data = profile_in.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(profile, field, value)
        
        await db.commit()
        await db.refresh(profile)
        
        # Invalidate cache
        cache_key = f"user:{current_user.id}:profiles"
        await redis_client.delete(cache_key)
        
        return {
            "id": profile.id,
            "name": profile.name,
            "avatar": profile.avatar,
            "is_kids": profile.is_kids,
            "is_active": profile.is_active,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/profile/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a profile (async, invalidates cache)"""
    try:
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.user_id == current_user.id
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        # Check if this is the last profile
        count_result = await db.execute(
            select(func.count(UserProfile.id)).where(UserProfile.user_id == current_user.id)
        )
        profile_count = count_result.scalar()
        
        if profile_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last profile")
        
        # If deleting active profile, set another as active
        if profile.is_active:
            other_result = await db.execute(
                select(UserProfile).where(
                    and_(
                        UserProfile.user_id == current_user.id,
                        UserProfile.id != profile_id
                    )
                )
            )
            other_profile = other_result.scalar_one_or_none()
            
            if other_profile:
                other_profile.is_active = True
        
        await db.delete(profile)
        await db.commit()
        
        # Invalidate cache
        cache_key = f"user:{current_user.id}:profiles"
        await redis_client.delete(cache_key)
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profile/set-active")
async def set_active_profile(
    request_body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Set active profile (async, invalidates cache)"""
    try:
        profile_id = request_body.get("profile_id")
        
        if not profile_id:
            raise HTTPException(status_code=400, detail="profile_id is required")
        
        # Check if profile exists
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.user_id == current_user.id
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        # Deactivate all profiles
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == current_user.id)
            .values(is_active=False)
        )
        
        # Activate selected profile
        profile.is_active = True
        
        await db.commit()
        await db.refresh(profile)
        
        # Invalidate cache
        cache_key = f"user:{current_user.id}:profiles"
        await redis_client.delete(cache_key)
        
        return {
            "message": "Active profile updated successfully",
            "profile": {
                "id": profile.id,
                "name": profile.name,
                "avatar": profile.avatar,
                "is_kids": profile.is_kids,
                "is_active": profile.is_active,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in set_active_profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile/active")
async def get_active_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get active profile (with Redis caching)"""
    try:
        # Try cache first
        cache_key = f"user:{current_user.id}:active_profile"
        cached_profile = await redis_client.get(cache_key)
        
        if cached_profile:
            logger.info(f"✅ Cache hit for user {current_user.id} active profile")
            return cached_profile
        
        # Cache miss - fetch from database
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.user_id == current_user.id,
                    UserProfile.is_active == True
                )
            )
        )
        active_profile = result.scalar_one_or_none()
        
        if not active_profile:
            # Get first profile or create default
            result = await db.execute(
                select(UserProfile).where(UserProfile.user_id == current_user.id)
            )
            active_profile = result.scalar_one_or_none()
            
            if not active_profile:
                active_profile = UserProfile(
                    user_id=current_user.id,
                    name=current_user.full_name or "Main Profile",
                    avatar="0",
                    is_kids=False,
                    is_active=True
                )
                db.add(active_profile)
                await db.commit()
                await db.refresh(active_profile)
        
        response = {
            "id": active_profile.id,
            "name": active_profile.name,
            "avatar": active_profile.avatar,
            "is_kids": active_profile.is_kids,
            "is_active": active_profile.is_active,
            "language_preference": active_profile.language_preference or "en",
            "subtitle_preference": getattr(active_profile, 'subtitle_preference', True),
            "autoplay_next": getattr(active_profile, 'autoplay_next', True),
            "pin_enabled": hasattr(active_profile, 'pin') and active_profile.pin is not None,
        }
        
        # Cache for 5 minutes
        await redis_client.set(cache_key, response, expire=300)
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting active profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get active profile"
        )


# ==================== USER SETTINGS ENDPOINTS (ASYNC + REDIS) ====================

@router.get("/settings/list")
async def get_user_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get user settings (with Redis caching)"""
    try:
        # Try cache first
        cache_key = f"user:{current_user.id}:settings"
        cached_settings = await redis_client.get(cache_key)
        
        if cached_settings:
            logger.info(f"✅ Cache hit for user {current_user.id} settings")
            return cached_settings
        
        # Cache miss - fetch from database
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            # Create default settings
            settings = UserSettings(
                user_id=current_user.id,
                cellular_data_usage='automatic',
                hdr_playback=False,
                allow_notifications=True,
                wifi_only_downloads=True,
                download_quality='standard',
                download_location='internal',
                autoplay_next=True,
                autoplay_previews=True,
                subtitle_preference=True,
                language_preference='en',
            )
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
            logger.info(f"✅ Created default settings for user: {current_user.id}")
        
        response = {
            "success": True,
            "settings": {
                "cellular_data_usage": settings.cellular_data_usage,
                "hdr_playback": settings.hdr_playback,
                "allow_notifications": settings.allow_notifications,
                "wifi_only_downloads": settings.wifi_only_downloads,
                "download_quality": settings.download_quality,
                "download_location": settings.download_location,
                "autoplay_next": settings.autoplay_next,
                "autoplay_previews": settings.autoplay_previews,
                "subtitle_preference": settings.subtitle_preference,
                "language_preference": settings.language_preference,
            }
        }
        
        # Cache for 10 minutes
        await redis_client.set(cache_key, response, expire=600)
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Error fetching settings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "message": "Failed to fetch user settings"}
        )


@router.post("/settings/update")
async def update_user_settings(
    settings_update: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update user settings (async, invalidates cache)"""
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = UserSettings(user_id=current_user.id)
            db.add(settings)
        
        # Update only provided fields
        update_data = settings_update.dict(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"success": False, "message": "No fields provided for update"}
            )
        
        for field, value in update_data.items():
            if hasattr(settings, field):
                setattr(settings, field, value)
        
        await db.commit()
        await db.refresh(settings)
        
        # Invalidate cache
        cache_key = f"user:{current_user.id}:settings"
        await redis_client.delete(cache_key)
        
        logger.info(f"✅ Settings updated for user: {current_user.id}")
        
        return {
            "success": True,
            "message": "Settings updated successfully",
            "settings": {
                "cellular_data_usage": settings.cellular_data_usage,
                "hdr_playback": settings.hdr_playback,
                "allow_notifications": settings.allow_notifications,
                "wifi_only_downloads": settings.wifi_only_downloads,
                "download_quality": settings.download_quality,
                "download_location": settings.download_location,
                "autoplay_next": settings.autoplay_next,
                "autoplay_previews": settings.autoplay_previews,
                "subtitle_preference": settings.subtitle_preference,
                "language_preference": settings.language_preference,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating settings: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "message": "Failed to update settings"}
        )


# ==================== CHANGE PASSWORD ====================

@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Change user password (async)"""
    try:
        # Verify current password
        if not verify_password(request.current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        # Validate new password
        if len(request.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 8 characters long"
            )
        
        # Update password
        current_user.hashed_password = get_password_hash(request.new_password)
        await db.commit()
        
        logger.info(f"✅ Password changed for user: {current_user.id}")
        
        return {"message": "Password changed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Password change failed: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )


# ==================== DEVICES MANAGEMENT (ASYNC + REDIS) ====================

@router.get("/devices/list")
async def get_user_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    user_agent: Optional[str] = Header(None),
):
    """Get all devices (with Redis caching)"""
    try:
        # Try cache first
        cache_key = f"user:{current_user.id}:devices"
        cached_devices = await redis_client.get(cache_key)
        
        if cached_devices:
            logger.info(f"✅ Cache hit for user {current_user.id} devices")
            return cached_devices
        
        # Cache miss - fetch from database
        result = await db.execute(
            select(UserDevice)
            .where(UserDevice.user_id == current_user.id)
            .order_by(UserDevice.last_active.desc())
        )
        devices = result.scalars().all()
        
        # Get current device info
        current_device_info = parse_user_agent(user_agent) if user_agent else None
        
        device_list = []
        for device in devices:
            is_current = False
            if current_device_info and device.device_name == current_device_info.get('device_name'):
                is_current = True
            
            device_list.append({
                "id": device.id,
                "device_name": device.device_name,
                "device_type": device.device_type,
                "browser": device.browser,
                "os": device.os,
                "ip_address": device.ip_address,
                "last_active": device.last_active.isoformat(),
                "created_at": device.created_at.isoformat(),
                "is_current": is_current
            })
        
        response = {
            "devices": device_list,
            "total": len(device_list)
        }
        
        # Cache for 2 minutes (devices change frequently)
        await redis_client.set(cache_key, response, expire=120)
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Failed to get devices: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve devices"
        )


@router.delete("/devices/{device_id}")
async def remove_device(
    device_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Remove a device (async, invalidates cache)"""
    try:
        result = await db.execute(
            select(UserDevice).where(
                and_(
                    UserDevice.id == device_id,
                    UserDevice.user_id == current_user.id
                )
            )
        )
        device = result.scalar_one_or_none()
        
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found"
            )
        
        device_name = device.device_name
        
        await db.delete(device)
        await db.commit()
        
        # Invalidate cache
        cache_key = f"user:{current_user.id}:devices"
        await redis_client.delete(cache_key)
        
        logger.info(f"🗑️ Device removed: {device_name}")
        
        return {"message": "Device removed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to remove device: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove device"
        )


# app/api/endpoints/users.py

# Add these endpoints after the existing ones:

# ==================== UPDATE ACTIVE PROFILE ====================

@router.patch("/profile/active/update")
async def update_active_profile(
    profile_update: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update the active profile"""
    try:
        # Get active profile
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.user_id == current_user.id,
                    UserProfile.is_active == True
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Active profile not found")
        
        # Update fields
        if profile_update.name is not None:
            profile.name = profile_update.name
        if profile_update.avatar is not None:
            profile.avatar = profile_update.avatar
        if profile_update.language_preference is not None:
            profile.language_preference = profile_update.language_preference
        if profile_update.subtitle_preference is not None:
            profile.subtitle_preference = profile_update.subtitle_preference
        if profile_update.autoplay_next is not None:
            profile.autoplay_next = profile_update.autoplay_next
        
        profile.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(profile)
        
        # Invalidate cache
        await redis_client.delete(f"user:{current_user.id}:profiles")
        await redis_client.delete(f"user:{current_user.id}:active_profile")
        
        return {
            "message": "Profile updated successfully",
            "profile": {
                "id": profile.id,
                "name": profile.name,
                "avatar": profile.avatar,
                "is_kids": profile.is_kids,
                "is_active": profile.is_active,
                "language_preference": profile.language_preference,
                "subtitle_preference": profile.subtitle_preference,
                "autoplay_next": profile.autoplay_next,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating active profile: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )


# ==================== PROFILE PIN MANAGEMENT ====================

# app/api/endpoints/users.py

@router.post("/profile/active/set-pin")
async def set_profile_pin(
    pin_request: ProfilePinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Set PIN for the active profile"""
    try:
        # Get ACTIVE profile (don't require profile_id from request)
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.user_id == current_user.id,
                    UserProfile.is_active == True
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Active profile not found")
        
        # Validate PIN (4-6 digits)
        if not pin_request.pin.isdigit() or len(pin_request.pin) < 4 or len(pin_request.pin) > 6:
            raise HTTPException(
                status_code=400,
                detail="PIN must be 4-6 digits"
            )
        
        # Hash the PIN
        profile.pin = get_password_hash(pin_request.pin)
        profile.updated_at = datetime.utcnow()
        
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete(f"user:{current_user.id}:profiles")
        await redis_client.delete(f"user:{current_user.id}:active_profile")
        
        return {"message": "PIN set successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting PIN: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set PIN"
        )
        
@router.post("/profile/{profile_id}/verify-pin")
async def verify_profile_pin(
    profile_id: int,
    pin_request: ProfilePinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Verify PIN for a profile"""
    try:
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.user_id == current_user.id
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        if not profile.pin:
            raise HTTPException(status_code=400, detail="No PIN set for this profile")
        
        # Verify PIN
        if not verify_password(pin_request.pin, profile.pin):
            raise HTTPException(status_code=401, detail="Incorrect PIN")
        
        # ✅ Return proper response format
        return {
            "message": "PIN verified successfully",
            "verified": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying PIN: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify PIN"
        )
    

@router.delete("/profile/active/remove-pin")
async def remove_profile_pin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Remove PIN from the active profile"""
    try:
        # Get ACTIVE profile
        result = await db.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.user_id == current_user.id,
                    UserProfile.is_active == True
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Active profile not found")
        
        profile.pin = None
        profile.updated_at = datetime.utcnow()
        
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete(f"user:{current_user.id}:profiles")
        await redis_client.delete(f"user:{current_user.id}:active_profile")
        
        return {"message": "PIN removed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing PIN: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove PIN"
        )


# ==================== UPDATE EMAIL/PHONE ====================

@router.post("/update-email")
async def update_email(
    request: UpdateEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update user email"""
    try:
        # Verify password
        if not verify_password(request.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password"
            )
        
        # Check if email already exists
        result = await db.execute(
            select(User).where(
                and_(
                    User.email == request.new_email,
                    User.id != current_user.id
                )
            )
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use"
            )
        
        current_user.email = request.new_email
        current_user.email_verified = False  # Require reverification
        current_user.updated_at = datetime.utcnow()
        
        await db.commit()
        
        logger.info(f"✅ Email updated for user: {current_user.id}")
        
        return {"message": "Email updated successfully. Please verify your new email."}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Email update failed: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update email"
        )


@router.post("/update-phone")
async def update_phone(
    request: UpdatePhoneRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update user phone - sends OTP"""
    try:
        # Verify password
        if not verify_password(request.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password"
            )
        
        # Normalize phone
        import re
        clean_phone = re.sub(r'[^\d+]', '', request.new_phone)
        if clean_phone.startswith('0'):
            clean_phone = '+255' + clean_phone[1:]
        elif clean_phone.startswith('255'):
            clean_phone = '+' + clean_phone
        elif not clean_phone.startswith('+'):
            clean_phone = '+255' + clean_phone
        
        # Check if phone already exists
        result = await db.execute(
            select(User).where(
                and_(
                    User.phone == clean_phone,
                    User.id != current_user.id
                )
            )
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone number already in use"
            )
        
        # Generate and send OTP
        otp_code = generate_otp(6)
        
        otp_session = OtpSession(
            user_id=current_user.id,
            otp_code=otp_code,
            email_or_phone=clean_phone,
            is_used=False,
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        db.add(otp_session)
        await db.commit()
        
        # Send OTP
        await send_otp_sms(clean_phone, otp_code)
        
        logger.info(f"✅ Phone update OTP sent to: {clean_phone}")
        
        return {
            "message": f"Verification code sent to {clean_phone}",
            "phone": clean_phone
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Phone update failed: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update phone"
        )


@router.post("/verify-phone-update")
async def verify_phone_update(
    request: VerifyPhoneRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Verify OTP and update phone"""
    try:  
        # Get latest OTP
        result = await db.execute(
            select(OtpSession)
            .where(
                and_(
                    OtpSession.user_id == current_user.id,
                    OtpSession.is_used == False,
                    OtpSession.expires_at > datetime.utcnow()
                )
            )
            .order_by(OtpSession.created_at.desc())
            .limit(1)
        )
        otp_session = result.scalar_one_or_none()
        
        if not otp_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OTP expired or not found"
            )
        
        if otp_session.otp_code != request.otp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid OTP"
            )
        
        # Update phone
        current_user.phone = otp_session.email_or_phone
        current_user.phone_verified = True
        current_user.updated_at = datetime.utcnow()
        
        # Mark OTP as used
        otp_session.is_used = True
        otp_session.verified_at = datetime.utcnow()
        
        await db.commit()
        
        logger.info(f"✅ Phone updated for user: {current_user.id}")
        
        return {"message": "Phone number updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Phone verification failed: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify phone"
        )


# ==================== ADMIN USER MANAGEMENT ====================

@router.post("/admin/create")
async def create_user_admin(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Create a new user (admin only)"""
    try:
        # Check if user exists
        result = await db.execute(
            select(User).where(
                or_(
                    User.email == user_data.email,
                    User.phone == user_data.phone if hasattr(user_data, 'phone') and user_data.phone else False
                )
            )
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email or phone already exists"
            )
        
        # Create user
        new_user = User(
            email=user_data.email,
            full_name=user_data.full_name,
            hashed_password=get_password_hash(user_data.password),
            phone=getattr(user_data, 'phone', None),
            role=getattr(user_data, 'role', UserRole.CLIENT),
            is_active=getattr(user_data, 'is_active', True),
            created_at=datetime.utcnow()
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        # Invalidate cache
        await redis_client.delete("admin:user_statistics")
        
        logger.info(f"✅ User created by admin: {new_user.id}")
        
        return {
            "data": {
                "id": new_user.id,
                "message": "User created successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/admin/view/{user_id}")
async def get_user_by_id_admin(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Get user by ID (admin only)"""
    try:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "phone": getattr(user, 'phone', None),
                "role": getattr(user, 'role', 'client'),
                "is_active": user.is_active,
                "is_superuser": getattr(user, 'is_superuser', False),
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/admin/update/{user_id}")
async def update_user_admin(
    user_id: int,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Update user (admin only)"""
    try:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Update fields
        update_data = user_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field == 'password' and value:
                user.hashed_password = get_password_hash(value)
            elif hasattr(user, field):
                setattr(user, field, value)
        
        user.updated_at = datetime.utcnow()
        
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete("admin:user_statistics")
        
        return {
            "data": {
                "id": user.id,
                "message": "User updated successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/admin/toggle-status/{user_id}")
async def toggle_user_status_admin(
    user_id: int,
    status_update: UserStatusUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Toggle user status (admin only)"""
    try:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user.is_active = status_update.is_active
        user.updated_at = datetime.utcnow()
        
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete("admin:user_statistics")
        
        return {
            "data": {
                "message": f"User {'activated' if status_update.is_active else 'deactivated'} successfully"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/admin/remove/{user_id}")
async def delete_user_admin(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Delete user (admin only)"""
    try:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        await db.delete(user)
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete("admin:user_statistics")
        
        return {
            "success": True,
            "message": "User deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/admin/bulk/toggle-status")
async def bulk_toggle_user_status(
    is_active: bool,
    bulk_action: BulkUserAction,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Bulk toggle user status (admin only)"""
    try:
        await db.execute(
            update(User)
            .where(User.id.in_(bulk_action.user_ids))
            .values(is_active=is_active, updated_at=datetime.utcnow())
        )
        
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete("admin:user_statistics")
        
        return {
            "success": True,
            "message": f"{len(bulk_action.user_ids)} users {'activated' if is_active else 'deactivated'}",
            "updated_count": len(bulk_action.user_ids)
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/admin/bulk/remove")
async def bulk_delete_users(
    bulk_action: BulkUserAction,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Bulk delete users (admin only)"""
    try:
        await db.execute(
            delete(User).where(User.id.in_(bulk_action.user_ids))
        )
        
        await db.commit()
        
        # Invalidate cache
        await redis_client.delete("admin:user_statistics")
        
        return {
            "success": True,
            "message": f"{len(bulk_action.user_ids)} users deleted",
            "deleted_count": len(bulk_action.user_ids)
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/admin/export")
async def export_users_admin(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Export all users to CSV (admin only)"""
    try:
        import csv
        import io
        
        result = await db.execute(select(User))
        users = result.scalars().all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['ID', 'Email', 'Full Name', 'Phone', 'Role', 'Active', 'Created At'])
        
        # Data
        for user in users:
            writer.writerow([
                user.id,
                user.email,
                user.full_name,
                getattr(user, 'phone', ''),
                getattr(user, 'role', 'client'),
                user.is_active,
                user.created_at.isoformat() if user.created_at else ''
            ])
        
        return output.getvalue()
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ==================== ADMIN ENDPOINTS (ASYNC + REDIS) ====================

@router.get("/admin/statistics")
async def get_admin_user_statistics(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Get user statistics with Redis caching (1 minute)"""
    try:
        # Try cache first
        cache_key = "admin:user_statistics"
        cached_stats = await redis_client.get(cache_key)
        
        if cached_stats:
            logger.info("✅ Cache hit for admin statistics")
            return cached_stats
        
        # Execute queries SEQUENTIALLY
        total_result = await db.execute(select(func.count(User.id)))
        total_users = total_result.scalar() or 0
        
        active_result = await db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        active_users = active_result.scalar() or 0
        
        admin_result = await db.execute(
            select(func.count(User.id)).where(
                or_(User.role == 'admin', User.is_superuser == True)
            )
        )
        admin_users = admin_result.scalar() or 0
        
        client_result = await db.execute(
            select(func.count(User.id)).where(User.role == 'client')
        )
        client_users = client_result.scalar() or 0
        
        first_day = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_result = await db.execute(
            select(func.count(User.id)).where(User.created_at >= first_day)
        )
        new_users_this_month = new_result.scalar() or 0
        
        stats = {
            "total_users": total_users,
            "active_users": active_users,
            "inactive_users": total_users - active_users,
            "admin_users": admin_users,
            "client_users": client_users,
            "new_users_this_month": new_users_this_month
        }
        
        # Cache for 1 minute
        await redis_client.set(cache_key, stats, expire=60)
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/admin/all")
async def get_all_users_admin(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """Get all users with pagination (async, with Redis caching)"""
    try:
        # Create cache key based on params
        cache_key = f"admin:users:skip={skip}:limit={limit}:search={search}:role={role}:active={is_active}"
        cached_data = await redis_client.get(cache_key)
        
        if cached_data:
            logger.info("✅ Cache hit for users list")
            return cached_data
        
        # Build query
        query = select(User)
        
        if search:
            search_term = f"%{search}%"
            filters = [User.email.ilike(search_term), User.full_name.ilike(search_term)]
            if hasattr(User, 'phone'):
                filters.append(User.phone.ilike(search_term))
            query = query.where(or_(*filters))
        
        if role and role in ['admin', 'client']:
            query = query.where(User.role == role)
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        # Get total and users SEQUENTIALLY
        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()
        
        users_result = await db.execute(
            query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        )
        users = users_result.scalars().all()
        
        users_list = []
        for u in users:
            users_list.append({
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": getattr(u, 'role', 'client'),
                "is_active": u.is_active,
                "is_superuser": getattr(u, 'is_superuser', False),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            })
        
        response = {
            "users": users_list,
            "total": total,
            "skip": skip,
            "limit": limit
        }
        
        # Cache for 30 seconds
        await redis_client.set(cache_key, response, expire=30)
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )