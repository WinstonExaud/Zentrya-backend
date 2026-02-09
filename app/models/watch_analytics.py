"""
Zentrya Watch-Time Analytics Models
Netflix-grade tracking system for views, watch-time, and producer payments
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from ..database import Base


class WatchSession(Base):
    """
    Track individual watch sessions for watch-time analytics
    
    Business Rules:
    - Movies: One profile = One view per movie (unique)
    - Series: One profile = One view per series (any episode counts)
    - Episodes: Each episode tracked separately for watch-time
    - First watch = Actual Watch Time (100% value)
    - Rewatches after 24h = Weighted Watch Time (50-30%)
    - Same-day rewatches = 0% (fraud prevention)
    """
    __tablename__ = "watch_sessions"

    id = Column(Integer, primary_key=True, index=True)
    
    # References
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=True)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=True)
    episode_id = Column(Integer, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    
    # Session tracking
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    device_id = Column(String(255), nullable=True)  # For multi-device tracking
    
    # Watch metrics
    watch_time_seconds = Column(Integer, default=0)  # Total seconds watched in this session
    video_duration_seconds = Column(Integer, nullable=False)  # Total video length
    completion_percentage = Column(Float, default=0.0)  # % completed (0-100)
    
    # Session metadata
    is_first_watch = Column(Boolean, default=True)  # True = Actual, False = Rewatch
    is_completed = Column(Boolean, default=False)  # Watched >90%
    quality_level = Column(String(20), nullable=True)  # 480p, 720p, 1080p, 4k
    
    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_position_update = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="watch_sessions")
    movie = relationship("Movie", back_populates="watch_sessions")
    series = relationship("Series", back_populates="watch_sessions")
    episode = relationship("Episode", back_populates="watch_sessions")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_watch_user_movie', 'user_id', 'movie_id'),
        Index('idx_watch_user_series', 'user_id', 'series_id'),
        Index('idx_watch_started', 'started_at'),
        Index('idx_watch_first', 'is_first_watch'),
    )


class MovieAnalytics(Base):
    """
    Aggregated analytics per movie for producer dashboards
    Updated via background jobs (hourly/daily)
    """
    __tablename__ = "movie_analytics"

    id = Column(Integer, primary_key=True, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # View metrics (Discovery & Trending)
    total_views = Column(Integer, default=0)  # Unique profiles
    rewatched_views = Column(Integer, default=0)  # Profiles who watched 2+ times
    
    # Watch-time metrics (Payment Calculation)
    actual_watch_time_minutes = Column(Float, default=0.0)  # First watch only (100%)
    rewatched_watch_time_minutes = Column(Float, default=0.0)  # Rewatch total (weighted)
    effective_watch_time_minutes = Column(Float, default=0.0)  # Payment basis
    
    # Engagement metrics
    average_completion_rate = Column(Float, default=0.0)  # Average % watched
    total_sessions = Column(Integer, default=0)  # All sessions
    unique_viewers = Column(Integer, default=0)  # Same as total_views
    
    # Quality insights
    most_watched_quality = Column(String(20), nullable=True)  # Most popular quality
    peak_watch_hour = Column(Integer, nullable=True)  # 0-23 (for recommendations)
    
    # Payment tracking
    last_payment_month = Column(String(7), nullable=True)  # YYYY-MM
    monthly_earnings_tzs = Column(Float, default=0.0)  # Last payment amount
    
    # Timestamps
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    movie = relationship("Movie", back_populates="analytics")
    
    __table_args__ = (
        Index('idx_analytics_movie', 'movie_id'),
        Index('idx_analytics_effective_time', 'effective_watch_time_minutes'),
        Index('idx_analytics_updated', 'last_updated'),
    )


class SeriesAnalytics(Base):
    """
    Aggregated analytics per series for producer dashboards
    
    Key Differences from Movies:
    - View = One profile per SERIES (not per episode)
    - Watch-time = Sum of all episode watch-times
    - Episodes tracked separately for insights
    """
    __tablename__ = "series_analytics"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # View metrics (Discovery & Trending) - SERIES LEVEL
    total_views = Column(Integer, default=0)  # Unique profiles who watched ANY episode
    rewatched_views = Column(Integer, default=0)  # Profiles who watched 2+ episodes
    
    # Watch-time metrics (Payment Calculation) - SUM OF ALL EPISODES
    actual_watch_time_minutes = Column(Float, default=0.0)  # First watch only (100%)
    rewatched_watch_time_minutes = Column(Float, default=0.0)  # Rewatch total (weighted)
    effective_watch_time_minutes = Column(Float, default=0.0)  # Payment basis
    
    # Engagement metrics
    average_completion_rate = Column(Float, default=0.0)  # Average % of series watched
    total_sessions = Column(Integer, default=0)  # All episode sessions
    unique_viewers = Column(Integer, default=0)  # Same as total_views
    total_episodes_watched = Column(Integer, default=0)  # Total episode completions
    
    # Series-specific metrics
    average_episodes_per_viewer = Column(Float, default=0.0)  # Engagement depth
    binge_rate = Column(Float, default=0.0)  # % who watch 3+ episodes in 24h
    drop_off_episode = Column(Integer, nullable=True)  # Where most people stop
    
    # Quality insights
    most_watched_quality = Column(String(20), nullable=True)
    peak_watch_hour = Column(Integer, nullable=True)
    
    # Payment tracking
    last_payment_month = Column(String(7), nullable=True)  # YYYY-MM
    monthly_earnings_tzs = Column(Float, default=0.0)  # Last payment amount
    
    # Timestamps
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    series = relationship("Series", back_populates="analytics")
    
    __table_args__ = (
        Index('idx_series_analytics_series', 'series_id'),
        Index('idx_series_analytics_effective_time', 'effective_watch_time_minutes'),
        Index('idx_series_analytics_updated', 'last_updated'),
    )


class EpisodeAnalytics(Base):
    """
    Aggregated analytics per episode for detailed insights
    
    Used for:
    - Identifying drop-off points
    - Episode-level performance
    - Renewal decisions
    - NOT used directly for payment (rolled up to series)
    """
    __tablename__ = "episode_analytics"

    id = Column(Integer, primary_key=True, index=True)
    episode_id = Column(Integer, ForeignKey("episodes.id", ondelete="CASCADE"), unique=True, nullable=False)
    series_id = Column(Integer, ForeignKey("series.id", ondelete="CASCADE"), nullable=False)
    
    # Watch-time metrics (rolled up to series for payment)
    actual_watch_time_minutes = Column(Float, default=0.0)  # First watch only
    rewatched_watch_time_minutes = Column(Float, default=0.0)  # Rewatches
    effective_watch_time_minutes = Column(Float, default=0.0)  # Payment contribution
    
    # Episode-specific metrics
    total_starts = Column(Integer, default=0)  # How many started this episode
    total_completions = Column(Integer, default=0)  # How many finished (>90%)
    completion_rate = Column(Float, default=0.0)  # % who finished
    average_watch_percentage = Column(Float, default=0.0)  # Average % watched
    
    # Engagement insights
    total_sessions = Column(Integer, default=0)
    unique_viewers = Column(Integer, default=0)
    average_rewatch_count = Column(Float, default=0.0)  # How many times rewatched
    
    # Drop-off analysis
    drop_off_at_25 = Column(Integer, default=0)  # Dropped at 25%
    drop_off_at_50 = Column(Integer, default=0)  # Dropped at 50%
    drop_off_at_75 = Column(Integer, default=0)  # Dropped at 75%
    
    # Quality metrics
    most_watched_quality = Column(String(20), nullable=True)
    
    # Timestamps
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    episode = relationship("Episode", back_populates="analytics")
    series = relationship("Series")
    
    __table_args__ = (
        Index('idx_episode_analytics_episode', 'episode_id'),
        Index('idx_episode_analytics_series', 'series_id'),
        Index('idx_episode_analytics_effective_time', 'effective_watch_time_minutes'),
        Index('idx_episode_analytics_updated', 'last_updated'),
    )


class MonthlyPayment(Base):
    """
    Monthly producer payment records
    Generated at end of each month
    """
    __tablename__ = "monthly_payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Payment period
    month = Column(String(7), nullable=False)  # YYYY-MM
    year = Column(Integer, nullable=False)
    month_number = Column(Integer, nullable=False)  # 1-12
    
    # Producer info
    producer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    producer_name = Column(String(255), nullable=False)
    
    # Content metrics
    total_movies = Column(Integer, default=0)
    total_series = Column(Integer, default=0)
    
    # Watch-time breakdown
    effective_watch_time_minutes = Column(Float, default=0.0)
    actual_watch_time_minutes = Column(Float, default=0.0)
    rewatched_watch_time_minutes = Column(Float, default=0.0)
    
    # Payment calculation
    platform_total_watch_time = Column(Float, nullable=False)  # All content
    producers_pool_tzs = Column(Float, nullable=False)  # 60% of revenue
    payment_percentage = Column(Float, default=0.0)  # Producer's share
    payment_amount_tzs = Column(Float, default=0.0)  # Final payment
    
    # Status
    payment_status = Column(String(20), default="pending")  # pending, processed, paid
    payment_date = Column(DateTime, nullable=True)
    payment_reference = Column(String(100), nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="monthly_payments", foreign_keys=[user_id])
    producer = relationship("User", foreign_keys=[producer_id])

    __table_args__ = (
        UniqueConstraint('producer_id', 'month', name='unique_producer_month'),
        Index('idx_payment_month', 'month'),
        Index('idx_payment_producer', 'producer_id'),
        Index('idx_payment_status', 'payment_status'),
    )