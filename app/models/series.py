from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database import Base

# Many-to-many association table for series and genress
series_genres = Table(
    'series_genres',
    Base.metadata,
    Column('series_id', Integer, ForeignKey('series.id', ondelete='CASCADE'), primary_key=True),
    Column('genre_id', Integer, ForeignKey('genres.id', ondelete='CASCADE'), primary_key=True)
)


class Series(Base):
    """
    Series model for TV shows and web series content
    """
    __tablename__ = "series"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Basic Information
    title = Column(String(255), index=True, nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=False)
    synopsis = Column(Text, nullable=True)
    
    # Media Files
    poster_url = Column(String(500), nullable=True, comment="Main poster/thumbnail image")
    banner_url = Column(String(500), nullable=True, comment="Wide banner image for hero sections")
    trailer_url = Column(String(500), nullable=True, comment="Trailer video URL")
    
    # Series Metadata
    total_seasons = Column(Integer, default=1, nullable=False, comment="Total number of seasons")
    total_episodes = Column(Integer, default=0, nullable=False, comment="Total number of episodes across all seasons")
    release_year = Column(Integer, nullable=True, comment="Year the series was first released")
    rating = Column(Float, default=0.0, nullable=False, comment="Average rating (0-5 or 0-10)")
    view_count = Column(Integer, default=0, nullable=False, comment="Total views across all episodes")
    
    # Content Information
    content_rating = Column(String(10), nullable=True, comment="Age rating (G, PG, PG-13, R, etc.)")
    language = Column(String(50), default="English", nullable=True, comment="Primary language")
    director = Column(String(255), nullable=True, comment="Main director(s)")
    production = Column(String(255), nullable=True, comment="Production company")
    
    # Foreign Keys
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Status Flags
    is_active = Column(Boolean, default=True, nullable=False, comment="Whether series is publicly visible")
    is_featured = Column(Boolean, default=False, nullable=False, comment="Whether to feature on homepage")
    is_completed = Column(Boolean, default=False, nullable=False, comment="Whether all episodes are released")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True) 
    
    # Relationships
    category = relationship("Category", back_populates="series")
    genres = relationship("Genre", secondary=series_genres, back_populates="series")
    episodes = relationship("Episode", back_populates="series", cascade="all, delete-orphan", order_by="Episode.season_number, Episode.episode_number")
    my_list_items = relationship("MyList", back_populates="series", cascade="all, delete-orphan")
    downloads = relationship("UserDownload", back_populates="series", cascade="all, delete-orphan")
    watch_sessions = relationship("WatchSession", back_populates="series", cascade="all, delete-orphan")
    analytics = relationship("SeriesAnalytics", back_populates="series", uselist=False, cascade="all, delete-orphan")

    
    def __repr__(self):
        return f"<Series(id={self.id}, title='{self.title}', seasons={self.total_seasons}, episodes={self.total_episodes})>"
    
    @property
    def status(self) -> str:
        """
        Computed property to determine series status
        Returns: 'completed', 'ongoing', or 'draft'
        """
        if self.is_completed:
            return 'completed'
        elif not self.is_active:
            return 'draft'
        else:
            return 'ongoing'


class Episode(Base):
    """
    Episode model for individual episodes within a series
    """
    __tablename__ = "episodes"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Episode Identification
    episode_number = Column(Integer, nullable=False, comment="Episode number within the season")
    season_number = Column(Integer, nullable=False, default=1, comment="Season number")
    
    # Basic Information
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Media Files
    thumbnail_url = Column(String(500), nullable=True, comment="Episode thumbnail")
    video_url = Column(String(500), nullable=True, comment="Video file URL or streaming link")
    
    # Metadata
    duration = Column(Integer, nullable=True, comment="Duration in minutes")
    view_count = Column(Integer, default=0, nullable=False)
    
    # Foreign Keys
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Status
    status = Column(String(50), default="draft", nullable=False, comment="draft, published, processing")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    # Relationships
    series = relationship("Series", back_populates="episodes")

# Resume playback (legacy)
    watch_progress = relationship(
    "WatchProgress",
    back_populates="episode",
    cascade="all, delete-orphan"
    )

# Watch-time analytics
    watch_sessions = relationship("WatchSession", back_populates="episode", cascade="all, delete-orphan")
    analytics = relationship("EpisodeAnalytics", back_populates="episode", uselist=False, cascade="all, delete-orphan")
    downloads = relationship("UserDownload", back_populates="episode", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Episode(id={self.id}, S{self.season_number:02d}E{self.episode_number:02d}, title='{self.title}')>"
    
    @property
    def full_title(self) -> str:
        """
        Generate full episode title with season and episode numbers
        Example: "S01E03 - Episode Title"
        """
        return f"S{self.season_number:02d}E{self.episode_number:02d} - {self.title}"