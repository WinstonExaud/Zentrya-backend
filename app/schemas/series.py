from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class SeriesBase(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    synopsis: Optional[str] = None
    poster_url: Optional[str] = None
    banner_url: Optional[str] = None
    trailer_url: Optional[str] = None
    total_seasons: int = 1
    release_year: Optional[int] = None
    content_rating: Optional[str] = None
    category_id: Optional[int] = None
    is_active: bool = True
    is_featured: bool = False
    is_completed: bool = False

class SeriesCreate(SeriesBase):
    pass

class SeriesUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    synopsis: Optional[str] = None
    poster_url: Optional[str] = None
    banner_url: Optional[str] = None
    trailer_url: Optional[str] = None
    total_seasons: Optional[int] = None
    release_year: Optional[int] = None
    content_rating: Optional[str] = None
    category_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_completed: Optional[bool] = None

class SeriesInDBBase(SeriesBase):
    id: int
    total_episodes: int
    rating: float
    view_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Series(SeriesInDBBase):
    pass