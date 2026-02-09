from sqlalchemy import Column, Integer, String, DateTime, Enum as SQLEnum
from sqlalchemy.sql import func
from datetime import datetime
import enum

from ..database import Base


class WaitlistStatus(str, enum.Enum):
    """Waitlist entry status"""
    PENDING = "pending"
    NOTIFIED = "notified"
    CONVERTED = "converted"


class Waitlist(Base):
    """
    Waitlist entries from Coming Soon page
    """
    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True, index=True)
    
    # Contact Information
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    
    # Status - CHANGE THIS PART
    status = Column(
        SQLEnum(
            WaitlistStatus,
            values_callable=lambda obj: [e.value for e in obj],  # ← THIS IS THE KEY FIX
            name="waitliststatus",
            create_constraint=False
        ),
        nullable=False,
        default=WaitlistStatus.PENDING,
        server_default="pending"
    )
    
    # Position in waitlist
    position = Column(Integer, nullable=False, index=True)
    
    # Timestamps
    joined_at = Column(DateTime, nullable=False, default=func.now())
    notified_at = Column(DateTime, nullable=True)
    converted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    def __repr__(self):
        return f"<Waitlist(id={self.id}, position={self.position}, status={self.status})>"