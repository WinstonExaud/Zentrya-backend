# app/models/movie.py
"""
Movie model for streaming platform
✅ Updated with Watch-Time Analytics support
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey, JSON, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database import Base

# Association table for many-to-many relationship between movies and genres
movie_genres = Table(
    'movie_genres',
    Base.metadata,
    Column('movie_id', Integer, ForeignKey('movies.id'), primary_key=True),
    Column('genre_id', Integer, ForeignKey('genres.id'), primary_key=True)
)


class Movie(Base):
    """
    Movie model with full watch-time analytics support
    
    Features:
    - HLS video streaming
    - Genre associations
    - Watch-time tracking
    - User downloads
    - My List functionality
    - Producer analytics
    """
    __tablename__ = "movies"
    
    # ==================== PRIMARY KEY ====================
    id = Column(Integer, primary_key=True, index=True)
    
    # ==================== BASIC INFO ====================
    title = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    synopsis = Column(Text, nullable=True)
    
    # ==================== MEDIA URLS ====================
    poster_url = Column(String(500), nullable=True)
    banner_url = Column(String(500), nullable=True)
    video_url = Column(String(500), nullable=True)  # HLS master playlist URL
    trailer_url = Column(String(500), nullable=True)
    
    # ==================== MOVIE DETAILS ====================
    duration = Column(Integer, nullable=True)  # Duration in SECONDS (not minutes!)
    release_year = Column(Integer, nullable=True)
    rating = Column(Float, default=0.0)  # IMDb-style rating (0-10)
    content_rating = Column(String(10), nullable=True)  # G, PG, PG-13, R, etc.
    language = Column(String(50), default="English")
    
    # ==================== PRODUCTION INFO ====================
    director = Column(String(255), nullable=True)
    production = Column(String(255), nullable=True)
    cast = Column(JSON, nullable=True)  # Array of cast members: ["Actor 1", "Actor 2"]
    
    # ==================== METADATA ====================
    view_count = Column(Integer, default=0, index=True)  # Unique profile views
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    is_active = Column(Boolean, default=False, index=True)  # Ready for streaming
    is_featured = Column(Boolean, default=False, index=True)  # Show on homepage
    
    # ==================== TIMESTAMPS ====================
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # ==================== EXISTING RELATIONSHIPS ====================
    
    # Category relationship
    category = relationship(
        "Category",
        back_populates="movies",
        foreign_keys=[category_id]
    )
    
    # Genres relationship (many-to-many)
    genres = relationship(
        "Genre",
        secondary=movie_genres,
        back_populates="movies"
    )
    
    # Watch progress (legacy - for resume playback)
    watch_progress = relationship(
        "WatchProgress",
        back_populates="movie",
        cascade="all, delete-orphan"
    )
    
    # My List functionality
    my_list_items = relationship(
        "MyList",
        back_populates="movie",
        cascade="all, delete-orphan"
    )
    
    # User downloads
    downloads = relationship(
        "UserDownload",
        back_populates="movie",
        cascade="all, delete-orphan"
    )
    
    # ==================== NEW: WATCH-TIME ANALYTICS RELATIONSHIPS ====================
    
    # Watch sessions (tracks individual viewing sessions)
    watch_sessions = relationship(
        "WatchSession",
        back_populates="movie",
        cascade="all, delete-orphan",
        doc="Individual watch sessions for analytics and payment tracking"
    )
    
    # Movie analytics (aggregated statistics)
    analytics = relationship(
        "MovieAnalytics",
        back_populates="movie",
        uselist=False,  # One-to-one relationship
        cascade="all, delete-orphan",
        doc="Aggregated analytics: views, watch-time, earnings"
    )
    
    # ==================== HELPER METHODS ====================
    
    def __repr__(self):
        return f"<Movie(id={self.id}, title='{self.title}', active={self.is_active})>"
    
    @property
    def duration_minutes(self) -> int:
        """Convert duration from seconds to minutes"""
        if self.duration:
            return self.duration // 60
        return 0
    
    @property
    def is_ready_for_streaming(self) -> bool:
        """Check if movie has all required fields for streaming"""
        return all([
            self.video_url,
            self.duration,
            self.is_active
        ])
    
    @property
    def has_analytics(self) -> bool:
        """Check if movie has analytics data"""
        return self.analytics is not None
    
    def to_dict(self, include_analytics: bool = False) -> dict:
        """
        Convert movie to dictionary
        
        Args:
            include_analytics: Include analytics data in response
        
        Returns:
            Dictionary representation of movie
        """
        data = {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "description": self.description,
            "synopsis": self.synopsis,
            "poster_url": self.poster_url,
            "banner_url": self.banner_url,
            "trailer_url": self.trailer_url,
            "video_url": self.video_url,
            "duration": self.duration,
            "duration_minutes": self.duration_minutes,
            "release_year": self.release_year,
            "rating": self.rating,
            "content_rating": self.content_rating,
            "language": self.language,
            "director": self.director,
            "production": self.production,
            "cast": self.cast or [],
            "view_count": self.view_count,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "genres": [{"id": g.id, "name": g.name, "slug": g.slug} for g in self.genres],
            "is_active": self.is_active,
            "is_featured": self.is_featured,
            "is_ready_for_streaming": self.is_ready_for_streaming,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        
        # Include analytics if requested (for producer dashboards)
        if include_analytics and self.analytics:
            data["analytics"] = {
                "total_views": self.analytics.total_views,
                "rewatched_views": self.analytics.rewatched_views,
                "effective_watch_time_minutes": round(self.analytics.effective_watch_time_minutes, 2),
                "average_completion_rate": round(self.analytics.average_completion_rate, 2),
                "total_sessions": self.analytics.total_sessions,
                "monthly_earnings_tzs": self.analytics.monthly_earnings_tzs,
                "last_payment_month": self.analytics.last_payment_month,
            }
        
        return data


# ==================== NOTES FOR DEVELOPERS ====================
"""
IMPORTANT CHANGES FROM ORIGINAL MODEL:

1. ✅ duration is now in SECONDS (was minutes)
   - This is required for accurate watch-time tracking
   - Use duration_minutes property if you need minutes

2. ✅ Added watch_sessions relationship
   - Tracks individual viewing sessions
   - Used for analytics and fraud prevention

3. ✅ Added analytics relationship
   - One-to-one relationship with MovieAnalytics
   - Contains aggregated statistics for producer dashboards

4. ✅ Added helper methods
   - duration_minutes: Get duration in minutes
   - is_ready_for_streaming: Check if movie is streamable
   - has_analytics: Check if analytics exist
   - to_dict(): Convert to dictionary with optional analytics

5. ✅ view_count now represents UNIQUE PROFILE VIEWS
   - One profile = one view (forever)
   - Used for trending, not payments

MIGRATION NOTES:

If you have existing movies with duration in minutes:
```sql
-- Convert existing durations from minutes to seconds
UPDATE movies SET duration = duration * 60 WHERE duration IS NOT NULL;
```

USAGE EXAMPLES:

# Get movie with analytics
movie = db.query(Movie).options(
    selectinload(Movie.analytics)
).filter(Movie.id == movie_id).first()

# Convert to dict with analytics
movie_dict = movie.to_dict(include_analytics=True)

# Check if ready for streaming
if movie.is_ready_for_streaming:
    # Start watch session
    pass
"""