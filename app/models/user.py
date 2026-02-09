"""
ZENTRYA User Models - Complete Production Version
Includes PaymentIntent for Selcom payment flow tracking
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Enum as SQLEnum, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from enum import Enum
from .payment import Payment  # Add this line
from .notification import Notification
from ..database import Base


# ==================== ENUMS ====================

class UserRole(str, Enum):
    """User role enumeration"""
    ADMIN = "admin"
    CLIENT = "client"


class SubscriptionStatus(str, Enum):
    """Subscription status"""
    ACTIVE = "active"
    CANCELED = "canceled"
    EXPIRED = "expired"
    TRIAL = "trial"
    INACTIVE = "inactive"


class PaymentProvider(str, Enum):
    """Payment provider"""
    SELCOM = "selcom"
    MPESA = "mpesa"
    TIGOPESA = "tigopesa"
    AIRTEL_MONEY = "airtel_money"
    HALOPESA = "halopesa"


# ==================== USER MODEL ====================

class User(Base):
    """Main User model with complete subscription and payment fields"""
    __tablename__ = "users"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Authentication
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    hashed_password = Column(String(500), nullable=False)
    
    # Basic Info
    full_name = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    bio = Column(String(500), nullable=True)
    
    # Role & Status - FIXED: Added explicit enum names
    role = Column(SQLEnum(UserRole, name="user_role"), default=UserRole.CLIENT, index=True, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    is_superuser = Column(Boolean, default=False, index=True)
    
    # Verification
    email_verified = Column(Boolean, default=False)
    phone_verified = Column(Boolean, default=False)
    
    # Subscription Details - FIXED: Added explicit enum names
    subscription_status = Column(
        SQLEnum(SubscriptionStatus, name="subscription_status"), 
        default=SubscriptionStatus.INACTIVE, 
        index=True
    )
    subscription_plan = Column(String(100), nullable=True)  # mobile, basic, standard, premium
    subscription_start_date = Column(DateTime(timezone=True), nullable=True)
    subscription_end_date = Column(DateTime(timezone=True), nullable=True)
    next_billing_date = Column(DateTime(timezone=True), nullable=True, index=True)
    subscription_amount = Column(Float, default=0.0)
    subscription_currency = Column(String(3), default='TZS')
    auto_renew = Column(Boolean, default=True)
    
    # Payment Integration (Selcom) - FIXED: Added explicit enum names
    payment_provider = Column(SQLEnum(PaymentProvider, name="payment_provider"), default=PaymentProvider.SELCOM)
    payment_customer_id = Column(String(255), nullable=True, unique=True)
    payment_reference = Column(String(255), nullable=True, index=True)
    payment_last_four = Column(String(4), nullable=True)
    
    # Order Tracking
    order_id = Column(String(100), unique=True, index=True, nullable=True)
    
    # Security
    pin = Column(String(500), nullable=True)
    
    # Activity Tracking
    last_login = Column(DateTime(timezone=True), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ==================== RELATIONSHIPS ====================
    
    # Authentication & Settings
    otp_sessions = relationship("OtpSession", back_populates="user", cascade="all, delete-orphan")
    profiles = relationship("UserProfile", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    devices = relationship("UserDevice", back_populates="user", cascade="all, delete-orphan")

    # Content Interactions
    my_list = relationship("MyList", back_populates="user", cascade="all, delete-orphan")
    downloads = relationship("UserDownload", back_populates="user", cascade="all, delete-orphan")
    watch_progress = relationship("WatchProgress", back_populates="user", cascade="all, delete-orphan")
    
    # Payments
    payments = relationship("Payment", back_populates="user")
    
    # Media
    uploaded_avatars = relationship("Avatar", back_populates="uploader")
    
    # Notifications
    notifications = relationship("Notification", back_populates="user")
    notification_preferences = relationship("NotificationPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    # Watch Analytics - NEW
    watch_sessions = relationship(
        "WatchSession",
        back_populates="user",
        foreign_keys="WatchSession.user_id",
        cascade="all, delete-orphan"
    )
    
    # Producer Payments - NEW (for when user is receiving payments)
    monthly_payments = relationship(
        "MonthlyPayment",
        back_populates="user",
        foreign_keys="MonthlyPayment.user_id",
        cascade="all, delete-orphan"
    )
    
    # Producer Payments as Producer - NEW (for when user is the producer)
    producer_payments = relationship(
        "MonthlyPayment",
        foreign_keys="MonthlyPayment.producer_id",
        viewonly=True  # Read-only, no cascade
    )

    # ==================== METHODS ====================
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
    
    def is_admin(self) -> bool:
        """Check if user is admin"""
        return self.role == UserRole.ADMIN or self.is_superuser
    
    def is_client(self) -> bool:
        """Check if user is client"""
        return self.role == UserRole.CLIENT
    
    def has_active_subscription(self) -> bool:
        """Check if user has active subscription"""
        return self.subscription_status == SubscriptionStatus.ACTIVE
    
    def is_subscription_expired(self) -> bool:
        """Check if subscription has expired"""
        if not self.subscription_end_date:
            return False
        return datetime.utcnow() > self.subscription_end_date


# ==================== PAYMENT INTENT ====================

class PaymentIntent(Base):
    """
    Tracks payment flow from initiation to completion
    Used for Selcom payment status polling
    """
    __tablename__ = "payment_intents"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Order identification
    order_id = Column(String(100), unique=True, index=True, nullable=False)
    
    # Customer details
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=False)
    
    # Payment details
    amount = Column(Float, nullable=False)
    payment_provider = Column(String(50), nullable=False)  # airtel, mpesa, halopesa, tigopesa
    subscription_plan = Column(String(100), nullable=False)
    auto_renew = Column(Boolean, default=True)
    
    # Selcom tracking
    payment_reference = Column(String(255), nullable=True, index=True)
    transaction_id = Column(String(255), nullable=True, index=True)
    
    # Status tracking
    status = Column(String(50), default='pending', index=True)  # pending, completed, failed, expired
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<PaymentIntent(order_id={self.order_id}, status={self.status})>"
    
    def is_completed(self) -> bool:
        """Check if payment completed"""
        return self.status == 'completed'
    
    def is_pending(self) -> bool:
        """Check if payment pending"""
        return self.status == 'pending'


# ==================== OTP SESSION ====================

class OtpSession(Base):
    """OTP verification sessions"""
    __tablename__ = "otp_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # ✅ CHANGED: nullable=True (was nullable=False)
    otp_code = Column(String(6), nullable=False, index=True)
    email_or_phone = Column(String(255), nullable=False, index=True)
    is_used = Column(Boolean, default=False, index=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    user = relationship("User", back_populates="otp_sessions")
    
    def __repr__(self):
        return f"<OtpSession(user_id={self.user_id}, is_used={self.is_used})>"
    
    def is_expired(self) -> bool:
        """Check if OTP has expired"""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if OTP is still valid"""
        return not self.is_expired() and not self.is_used and self.attempts < self.max_attempts


# ==================== USER PROFILE ====================

class UserProfile(Base):
    """Multiple profiles per user (Netflix-style)"""
    __tablename__ = "user_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    avatar = Column(String(500), nullable=False)
    is_kids = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False, index=True)
    pin = Column(String(500), nullable=True)
    
    # Preferences
    language_preference = Column(String(10), default='en')
    subtitle_preference = Column(Boolean, default=True)
    autoplay_next = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="profiles")
    
    def __repr__(self):
        return f"<UserProfile(id={self.id}, name={self.name}, is_active={self.is_active})>"


# ==================== USER SETTINGS ====================

class UserSettings(Base):
    """App preferences and settings"""
    __tablename__ = "user_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    
    # Video Playback
    cellular_data_usage = Column(String(20), default='automatic')
    hdr_playback = Column(Boolean, default=False)
    
    # Notifications
    allow_notifications = Column(Boolean, default=True)
    
    # Downloads
    wifi_only_downloads = Column(Boolean, default=True)
    download_quality = Column(String(20), default='standard')
    download_location = Column(String(20), default='internal')
    
    # Playback
    autoplay_next = Column(Boolean, default=True)
    autoplay_previews = Column(Boolean, default=True)
    subtitle_preference = Column(Boolean, default=True)
    language_preference = Column(String(10), default='en')
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="settings")
    
    def __repr__(self):
        return f"<UserSettings(user_id={self.user_id})>"


# ==================== USER DEVICE ====================

class UserDevice(Base):
    """Device/Session tracking"""
    __tablename__ = "user_devices"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_name = Column(String(255), nullable=False)
    device_type = Column(String(50), nullable=False)
    browser = Column(String(100), nullable=True)
    os = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    location = Column(String(255), nullable=True)
    last_active = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    user = relationship("User", back_populates="devices")
    
    def __repr__(self):
        return f"<UserDevice(id={self.id}, user_id={self.user_id}, device_name={self.device_name})>"


# ==================== MY LIST ====================

class MyList(Base):
    """User's favorite/saved content"""
    __tablename__ = "my_list"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    user = relationship("User", back_populates="my_list")
    movie = relationship("Movie", back_populates="my_list_items")
    series = relationship("Series", back_populates="my_list_items")
    
    def __repr__(self):
        return f"<MyList(user_id={self.user_id}, movie_id={self.movie_id}, series_id={self.series_id})>"


# ==================== USER DOWNLOAD ====================

class UserDownload(Base):
    """Offline content downloads"""
    __tablename__ = "user_downloads"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Content references
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=True, index=True)
    series_id = Column(Integer, ForeignKey("series.id"), nullable=True, index=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=True, index=True)
    
    # Download details
    quality = Column(String(20), nullable=False)
    status = Column(String(20), default='pending', index=True)
    progress = Column(Float, default=0.0)
    downloaded_size = Column(Integer, default=0)
    total_size = Column(Integer, default=0)
    video_url = Column(String(500), nullable=True)
    download_path = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    user = relationship("User", back_populates="downloads")
    movie = relationship("Movie", back_populates="downloads")
    series = relationship("Series", back_populates="downloads")
    episode = relationship("Episode", back_populates="downloads")
    
    def __repr__(self):
        return f"<UserDownload(id={self.id}, status={self.status}, progress={self.progress}%)>"
    
    def is_expired(self) -> bool:
        """Check if download expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    def format_size(self) -> str:
        """Format size in human-readable format"""
        size = self.total_size or 0
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"