from sqlalchemy import Column, Integer, DateTime, ForeignKey, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database import Base

class ViewHistory(Base):
    __tablename__ = "view_history"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign Keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=True)
    
    # Viewing data
    watch_duration = Column(Integer, default=0)  # in seconds
    total_duration = Column(Integer, nullable=True)  # in seconds
    progress_percentage = Column(Float, default=0.0)
    
    # Timestamps
    watched_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="view_history")
    movie = relationship("Movie", back_populates="view_history")
    episode = relationship("Episode", back_populates="view_history")
