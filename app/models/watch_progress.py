# ================================
# COMPLETE WORKING watch_progress.py
# ================================
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database import Base



class WatchProgress(Base):
    """Watch Progress - Resume playback tracking"""
    __tablename__ = "watch_progress"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=True, index=True)
    episode_id = Column(Integer, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True)
    
    current_time = Column(Float, default=0.0)
    duration = Column(Float, default=0.0)
    percentage_watched = Column(Float, default=0.0)
    is_completed = Column(Boolean, default=False)
    
    last_watched = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships with explicit foreign_keys to prevent auto-detection
    user = relationship("User", back_populates="watch_progress", foreign_keys=[user_id])
    movie = relationship("Movie", back_populates="watch_progress", foreign_keys=[movie_id])
    episode = relationship("Episode", back_populates="watch_progress", foreign_keys=[episode_id])

