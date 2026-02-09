# app/models/genre.py
"""Genre model for movies and series"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database import Base
from .movie import movie_genres


class Genre(Base):
    __tablename__ = "genres"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(String(500), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    movies = relationship("Movie", secondary=movie_genres, back_populates="genres")
    series = relationship("Series", secondary="series_genres", back_populates="genres")
    
    def __repr__(self):
        return f"<Genre(id={self.id}, name={self.name})>"