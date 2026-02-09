from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class OtpSession(Base):
    """
    OTP Session model for storing OTP codes and verification status
    """
    __tablename__ = "otp_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    otp_code = Column(String(6), nullable=False, index=True)
    email_or_phone = Column(String(255), nullable=False, index=True)
    is_used = Column(Boolean, default=False, index=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    verified_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="otp_sessions")
    
    class Config:
        from_attributes = True
    
    def is_expired(self) -> bool:
        """Check if OTP has expired"""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if OTP is still valid"""
        return not self.is_expired() and not self.is_used and self.attempts < self.max_attempts