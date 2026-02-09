from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ..database import Base
from enum import Enum

class NotificationType(str, Enum):
    SYSTEM = "system"
    CONTENT = "content"
    RECOMMENDATION = "recommendation"
    SUBSCRIPTION = "subscription"
    DOWNLOAD = "download"
    PROMOTION = "promotion"
    ALERT = "alert"
    REMINDER = "reminder"
    INFO = "info"

class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

class NotificationDisplayType(str, Enum):
    POPUP = "popup"
    SCREEN = "screen"
    BOTH = "both"

class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # Content
    title = Column(String(200), nullable=False)
    body = Column(String(1000), nullable=False)
    type = Column(String(50), nullable=False)
    priority = Column(String(20), nullable=False, default="normal")
    
    # Display
    display_type = Column(String(20), nullable=False, default="popup")  # popup, screen, both
    auto_hide_delay = Column(Integer, nullable=False, default=5000)
    
    # Media
    image_url = Column(String(500), nullable=True)
    action_url = Column(String(500), nullable=True)
    action_label = Column(String(100), nullable=True, default="View Now")
    data = Column(JSON, nullable=True)
    
    # Delivery
    channels = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    
    # Tracking
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    
    # Scheduling
    scheduled_at = Column(DateTime, nullable=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="notifications")


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Channel preferences
    in_app_enabled = Column(Boolean, default=True)
    email_enabled = Column(Boolean, default=True)
    sms_enabled = Column(Boolean, default=False)
    
    # Category preferences
    system_notifications = Column(Boolean, default=True)
    content_notifications = Column(Boolean, default=True)
    recommendation_notifications = Column(Boolean, default=True)
    subscription_notifications = Column(Boolean, default=True)
    download_notifications = Column(Boolean, default=True)
    promotion_notifications = Column(Boolean, default=True)
    
    # Quiet hours
    quiet_hours_enabled = Column(Boolean, default=False)
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="notification_preferences")