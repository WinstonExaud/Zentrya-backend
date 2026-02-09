from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class MovieBase(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    synopsis: Optional[str] = None
    poster_url: Optional[str] = None
    banner_url: Optional[str] = None
    trailer_url: Optional[str] = None
    video_url: str
    duration: Optional[int] = None
    release_year: Optional[int] = None
    content_rating: Optional[str] = None
    category_id: Optional[int] = None
    is_active: bool = True
    is_featured: bool = False

class MovieCreate(MovieBase):
    pass

class MovieUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    synopsis: Optional[str] = None
    poster_url: Optional[str] = None
    banner_url: Optional[str] = None
    trailer_url: Optional[str] = None
    video_url: Optional[str] = None
    duration: Optional[int] = None
    release_year: Optional[int] = None
    content_rating: Optional[str] = None
    category_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None

class MovieInDBBase(MovieBase):
    id: int
    rating: float
    view_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Movie(MovieInDBBase):
    pass