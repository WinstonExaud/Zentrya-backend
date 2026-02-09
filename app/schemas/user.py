from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None

class UserInDBBase(UserBase):
    id: int
    is_superuser: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

class User(UserInDBBase):
    pass

class UserInDB(UserInDBBase):
    hashed_password: str

"""Add these schemas to your schemas/user.py file"""

from pydantic import BaseModel, validator
from typing import Optional
from datetime import datetime


# ==================== User Profile Schemas ====================

class UserProfileBase(BaseModel):
    """Base schema for UserProfile"""
    name: str
    avatar: str
    is_kids: bool = False
    language_preference: Optional[str] = None
    subtitle_preference: bool = True
    autoplay_next: bool = True


class UserProfileCreate(UserProfileBase):
    """Schema for creating a new profile"""
    pass
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Profile name cannot be empty')
        if len(v) > 100:
            raise ValueError('Profile name must be 100 characters or less')
        return v.strip()
    
    @validator('avatar')
    def avatar_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Avatar cannot be empty')
        return v.strip()


class UserProfileUpdate(BaseModel):
    """Schema for updating a profile - all fields optional"""
    name: Optional[str] = None
    avatar: Optional[str] = None
    is_kids: Optional[bool] = None
    language_preference: Optional[str] = None
    subtitle_preference: Optional[bool] = None
    autoplay_next: Optional[bool] = None
    
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if v is not None:
            if not v or not v.strip():
                raise ValueError('Profile name cannot be empty')
            if len(v) > 100:
                raise ValueError('Profile name must be 100 characters or less')
            return v.strip()
        return v


class UserProfile(UserProfileBase):
    """Schema for returning profile data"""
    id: int
    user_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True  # For Pydantic v2 (use orm_mode = True for v1)


class SetActiveProfileRequest(BaseModel):
    """Schema for setting active profile"""
    profile_id: int


# ==================== Update User Schema to Include Profiles ====================

class User(UserBase):
    """
    Updated User schema with profiles relationship
    Add this to your existing User schema or modify it
    """
    id: int
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_superuser: bool
    display_name: Optional[str] = None
    avatar: Optional[str] = None
    subscription_plan: Optional[str] = None
    payment_method: Optional[str] = None
    order_id: Optional[str] = None
    subscription_status: Optional[str] = None
    subscription_current_period_end: Optional[datetime] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    email_verified: bool = False
    phone_verified: bool = False
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    # Include profiles if needed
    profiles: Optional[list[UserProfile]] = None
    
    class Config:
        from_attributes = True  # For Pydantic v2    