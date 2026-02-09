from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class EpisodeBase(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    season_number: int
    episode_number: int
    thumbnail_url: Optional[str] = None
    video_url: str
    duration: Optional[int] = None
    series_id: int
    is_active: bool = True

class EpisodeCreate(EpisodeBase):
    pass

class EpisodeUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None
    duration: Optional[int] = None
    is_active: Optional[bool] = None

class EpisodeInDBBase(EpisodeBase):
    id: int
    view_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Episode(EpisodeInDBBase):
    pass
