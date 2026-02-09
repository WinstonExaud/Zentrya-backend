# app/models/avatar.py
"""
Avatar Model - Represents avatars in the library that users can select
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from ..database import Base


class Avatar(Base):
    """
    Avatar model for storing avatar images in the library.
    
    Admins upload avatars to the library, and users can select from these
    during signup or profile updates.
    """
    __tablename__ = "avatars"

    id = Column(Integer, primary_key=True, index=True)
    
    # Basic information
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Storage URLs
    avatar_url = Column(Text, nullable=False)  # Full size avatar URL
    thumbnail_url = Column(Text, nullable=True)  # Optional thumbnail URL
    
    # Categorization
    category = Column(String(100), nullable=True, index=True)
    tags = Column(Text, nullable=True)  # Comma-separated tags
    
    # File information
    file_size = Column(BigInteger, nullable=True)  # Size in bytes
    file_type = Column(String(100), nullable=True)  # MIME type
    
    # Status flags
    is_active = Column(Boolean, default=True, index=True)
    is_premium = Column(Boolean, default=False, index=True)
    
    # Usage tracking
    usage_count = Column(Integer, default=0)  # How many users have selected this avatar
    
    # Ownership
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    uploader = relationship("User", back_populates="uploaded_avatars")
    
    def __repr__(self):
        return f"<Avatar(id={self.id}, name='{self.name}', category='{self.category}')>"
    
    def to_dict(self):
        """Convert avatar instance to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "avatar_url": self.avatar_url,
            "thumbnail_url": self.thumbnail_url,
            "category": self.category,
            "tags": self.tags,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "is_active": self.is_active,
            "is_premium": self.is_premium,
            "usage_count": self.usage_count,
            "uploaded_by": self.uploaded_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def get_active_avatars(cls, db_session, category=None, is_premium=None):
        """Helper method to get active avatars with optional filters"""
        from sqlalchemy import and_
        
        query = db_session.query(cls).filter(cls.is_active == True)
        
        if category:
            query = query.filter(cls.category == category)
        
        if is_premium is not None:
            query = query.filter(cls.is_premium == is_premium)
        
        return query.order_by(cls.name).all()
    
    @classmethod
    def increment_usage(cls, db_session, avatar_id):
        """Increment usage count for an avatar"""
        avatar = db_session.query(cls).filter(cls.id == avatar_id).first()
        if avatar:
            avatar.usage_count += 1
            db_session.commit()
        return avatar
    
    @classmethod
    def get_categories(cls, db_session):
        """Get all distinct categories from active avatars"""
        from sqlalchemy import distinct
        
        categories = db_session.query(distinct(cls.category)).filter(
            cls.is_active == True,
            cls.category.isnot(None)
        ).all()
        
        return [category[0] for category in categories if category[0]]
    
    @classmethod
    def get_stats(cls, db_session):
        """Get avatar library statistics"""
        from sqlalchemy import func
        
        total_avatars = db_session.query(func.count(cls.id)).scalar() or 0
        active_avatars = db_session.query(func.count(cls.id)).filter(cls.is_active == True).scalar() or 0
        premium_avatars = db_session.query(func.count(cls.id)).filter(cls.is_premium == True).scalar() or 0
        total_usage = db_session.query(func.sum(cls.usage_count)).scalar() or 0
        
        # Category statistics
        categories = db_session.query(
            cls.category, 
            func.count(cls.id)
        ).filter(
            cls.is_active == True
        ).group_by(cls.category).all()
        
        category_stats = [
            {"category": category, "count": count} 
            for category, count in categories 
            if category
        ]
        
        return {
            "total_avatars": total_avatars,
            "active_avatars": active_avatars,
            "premium_avatars": premium_avatars,
            "total_usage": int(total_usage),
            "categories": category_stats
        }