"""
🔔 ZENTRYA NOTIFICATION SYSTEM - IN-APP, EMAIL & SMS
====================================================

Features:
✅ In-App Notifications (Pop-ups & Between-Screen)
✅ Email Notifications (SMTP)
✅ SMS Notifications (Beem Africa)
✅ Admin Management Dashboard
✅ User Notification Preferences
✅ Notification Templates
✅ Batch Notifications
✅ Read/Unread Status
✅ Notification History
✅ Analytics & Tracking

Note: Push notifications are handled separately via Firebase Console

Author: Winston - Zentrya
Version: 2.0.0
"""

from typing import Any, List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime, timedelta
from enum import Enum
import logging
import json

from ...database import get_db
from ...models.user import User
from ...api.deps import get_current_user, get_current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== ENUMS ====================

class NotificationType(str, Enum):
    """Notification types"""
    SYSTEM = "system"                    # System updates, maintenance
    CONTENT = "content"                  # New movies, series
    RECOMMENDATION = "recommendation"    # Personalized recommendations
    SUBSCRIPTION = "subscription"        # Subscription related
    DOWNLOAD = "download"                # Download status
    PROMOTION = "promotion"              # Promotions, offers
    ALERT = "alert"                      # Important alerts
    REMINDER = "reminder"                # Reminders
    INFO = "info"                        # General information


class NotificationPriority(str, Enum):
    """Notification priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationChannel(str, Enum):
    """Delivery channels"""
    IN_APP = "in_app"      # In-app notification (pop-up or screen)
    EMAIL = "email"        # Email notification
    SMS = "sms"            # SMS notification


class NotificationDisplayType(str, Enum):
    """How in-app notification should be displayed"""
    POPUP = "popup"              # Overlay pop-up (auto-dismiss)
    SCREEN = "screen"            # Full-screen/between-screen (requires user action)
    BOTH = "both"                # Both popup and screen


class NotificationStatus(str, Enum):
    """Notification delivery status"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


# ==================== PYDANTIC SCHEMAS ====================

class NotificationCreate(BaseModel):
    """Schema for creating a notification"""
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=1000)
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    channels: List[NotificationChannel] = [NotificationChannel.IN_APP]
    
    # Display type for in-app notifications
    display_type: NotificationDisplayType = NotificationDisplayType.POPUP
    
    # Optional fields
    image_url: Optional[str] = None
    action_url: Optional[str] = None  # Deep link or web URL
    action_label: Optional[str] = "View Now"
    data: Optional[Dict[str, Any]] = {}  # Additional data payload
    
    # Targeting
    user_ids: Optional[List[int]] = None  # Specific users
    all_users: bool = False              # Send to all users
    segment: Optional[str] = None         # User segment (premium, free, etc.)
    
    # Scheduling
    scheduled_at: Optional[datetime] = None  # Schedule for later
    expires_at: Optional[datetime] = None    # Expiration time
    
    # Auto-hide delay for popup (milliseconds)
    auto_hide_delay: int = 5000


class NotificationUpdate(BaseModel):
    """Schema for updating notification"""
    status: Optional[NotificationStatus] = None
    is_read: Optional[bool] = None
    read_at: Optional[datetime] = None


class NotificationResponse(BaseModel):
    """Notification response schema"""
    id: int
    user_id: Optional[int]
    title: str
    body: str
    type: NotificationType
    priority: NotificationPriority
    channels: List[str]
    display_type: str
    image_url: Optional[str]
    action_url: Optional[str]
    action_label: Optional[str]
    data: Optional[Dict]
    status: NotificationStatus
    is_read: bool
    read_at: Optional[datetime]
    created_at: datetime
    scheduled_at: Optional[datetime]
    sent_at: Optional[datetime]
    expires_at: Optional[datetime]
    auto_hide_delay: int
    
    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """List of notifications with pagination"""
    notifications: List[NotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int


class UserNotificationPreferences(BaseModel):
    """User notification preferences"""
    in_app_enabled: bool = True
    email_enabled: bool = True
    sms_enabled: bool = False
    
    # Category preferences
    system_notifications: bool = True
    content_notifications: bool = True
    recommendation_notifications: bool = True
    subscription_notifications: bool = True
    download_notifications: bool = True
    promotion_notifications: bool = True
    
    # Quiet hours
    quiet_hours_enabled: bool = False
    quiet_hours_start: Optional[str] = "22:00"  # Format: "HH:MM"
    quiet_hours_end: Optional[str] = "08:00"


class BatchNotificationCreate(BaseModel):
    """Batch notification creation"""
    notifications: List[NotificationCreate]


class NotificationStats(BaseModel):
    """Notification statistics"""
    total_sent: int
    total_delivered: int
    total_read: int
    total_failed: int
    delivery_rate: float
    read_rate: float


# ==================== NOTIFICATION SERVICE ====================

class NotificationService:
    """Service for sending notifications via different channels"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def send_email_notification(
        self,
        email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> bool:
        """
        Send email notification via SMTP
        """
        try:
            from ...config import settings
            
            if not settings.is_email_enabled:
                logger.warning("⚠️ Email not configured in settings")
                return False
            
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
            msg['To'] = email
            
            part1 = MIMEText(body, 'plain')
            msg.attach(part1)
            
            if html_body:
                part2 = MIMEText(html_body, 'html')
                msg.attach(part2)
            
            if settings.SMTP_SSL:
                import ssl
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as server:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.sendmail(msg['From'], email, msg.as_string())
            else:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                    if settings.SMTP_TLS:
                        server.starttls()
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.sendmail(msg['From'], email, msg.as_string())
            
            logger.info(f"📧 Email sent to {email}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Email failed to {email}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    async def send_sms_notification(
        self,
        phone: str,
        message: str
    ) -> bool:
        """
        Send SMS notification via Beem Africa
        """
        try:
            from ...config import settings
            
            if not settings.is_sms_enabled:
                logger.warning("⚠️ SMS not configured in settings")
                return False
            
            import requests
            import base64
            
            url = "https://apisms.beem.africa/v1/send"
            
            auth_string = f"{settings.BEEM_API_KEY}:{settings.BEEM_API_SECRET}"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            normalized_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            
            if not normalized_phone.startswith('+'):
                if normalized_phone.startswith('0'):
                    normalized_phone = '+255' + normalized_phone[1:]
                elif normalized_phone.startswith('255'):
                    normalized_phone = '+' + normalized_phone
                else:
                    normalized_phone = '+255' + normalized_phone
            
            payload = {
                "source_addr": settings.BEEM_SENDER_ID,
                "schedule_time": "",
                "encoding": 0,
                "message": message,
                "recipients": [
                    {
                        "recipient_id": "1",
                        "dest_addr": normalized_phone
                    }
                ]
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"📱 SMS sent to {normalized_phone}: {result}")
                return True
            else:
                logger.error(f"❌ Beem SMS failed: {response.status_code} - {response.text}")
                return False
            
        except Exception as e:
            logger.error(f"❌ SMS failed to {phone}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


def create_notification_email_html(
    title: str,
    body: str,
    image_url: Optional[str] = None,
    action_url: Optional[str] = None,
    action_label: str = "View Now"
) -> str:
    """Create beautiful HTML email template"""
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background-color: #f4f4f4;
            }}
            .email-container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
            }}
            .header {{
                background: linear-gradient(135deg, #000000 0%, #1a1a1a 100%);
                padding: 30px 20px;
                text-align: center;
            }}
            .logo {{
                color: #D4A017;
                font-size: 32px;
                font-weight: bold;
                margin: 0;
            }}
            .content {{
                padding: 40px 30px;
            }}
            .notification-title {{
                color: #000000;
                font-size: 24px;
                font-weight: bold;
                margin: 0 0 20px 0;
            }}
            .notification-body {{
                color: #333333;
                font-size: 16px;
                line-height: 1.6;
                margin: 0 0 30px 0;
            }}
            .notification-image {{
                width: 100%;
                max-width: 540px;
                height: auto;
                border-radius: 8px;
                margin: 0 0 30px 0;
            }}
            .cta-button {{
                display: inline-block;
                padding: 14px 32px;
                background-color: #D4A017;
                color: #000000 !important;
                text-decoration: none;
                font-weight: bold;
                border-radius: 6px;
                font-size: 16px;
            }}
            .footer {{
                background-color: #f8f8f8;
                padding: 30px;
                text-align: center;
                color: #666666;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <h1 class="logo">ZENTRYA</h1>
                <p style="color: #ffffff; font-size: 14px; margin: 5px 0 0 0;">
                    The Future of Technology in Tanzania
                </p>
            </div>
            
            <div class="content">
                <h2 class="notification-title">{title}</h2>
    """
    
    if image_url:
        html += f'<img src="{image_url}" alt="{title}" class="notification-image">'
    
    html += f'<p class="notification-body">{body}</p>'
    
    if action_url:
        html += f'<a href="{action_url}" class="cta-button">{action_label}</a>'
    
    html += """
            </div>
            
            <div class="footer">
                <p>© 2026 Zentrya. All rights reserved.<br>Dar es Salaam, Tanzania</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


# ==================== USER ENDPOINTS ====================

@router.get("/user/list", response_model=NotificationListResponse)
async def get_user_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[NotificationType] = None,
    unread_only: bool = False,
    display_type: Optional[NotificationDisplayType] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user's notifications with pagination
    
    **User Endpoint**
    """
    try:
        from ...models.notification import Notification
        
        query = db.query(Notification).filter(Notification.user_id == current_user.id)
        
        if type:
            query = query.filter(Notification.type == type.value)
        
        if unread_only:
            query = query.filter(Notification.is_read == False)
        
        if display_type:
            query = query.filter(Notification.display_type == display_type.value)
        
        total = query.count()
        unread_count = db.query(func.count(Notification.id)).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        ).scalar() or 0
        
        skip = (page - 1) * page_size
        notifications = query.order_by(desc(Notification.created_at)).offset(skip).limit(page_size).all()
        
        logger.info(f"📬 User {current_user.id} fetched {len(notifications)} notifications")
        
        return {
            "notifications": notifications,
            "total": total,
            "unread_count": unread_count,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching notifications: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch notifications"
        )


@router.get("/user/popup")
async def get_popup_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get unread popup notifications for current user
    
    Returns only popup and both types that haven't been read yet
    
    **User Endpoint**
    """
    try:
        from ...models.notification import Notification
        
        notifications = db.query(Notification).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
            Notification.display_type.in_(['popup', 'both']),
            or_(
                Notification.expires_at.is_(None),
                Notification.expires_at > datetime.utcnow()
            )
        ).order_by(desc(Notification.created_at)).limit(5).all()
        
        logger.info(f"📬 Fetched {len(notifications)} popup notifications for user {current_user.id}")
        
        return {"notifications": notifications}
        
    except Exception as e:
        logger.error(f"❌ Error fetching popup notifications: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch popup notifications"
        )


@router.get("/user/screen")
async def get_screen_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get unread screen/between-screen notifications
    
    Returns only screen and both types that require user action
    
    **User Endpoint**
    """
    try:
        from ...models.notification import Notification
        
        notifications = db.query(Notification).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
            Notification.display_type.in_(['screen', 'both']),
            or_(
                Notification.expires_at.is_(None),
                Notification.expires_at > datetime.utcnow()
            )
        ).order_by(desc(Notification.priority), desc(Notification.created_at)).all()
        
        logger.info(f"📬 Fetched {len(notifications)} screen notifications for user {current_user.id}")
        
        return {"notifications": notifications}
        
    except Exception as e:
        logger.error(f"❌ Error fetching screen notifications: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch screen notifications"
        )


@router.put("/user/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark notification as read"""
    try:
        from ...models.notification import Notification
        
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        ).first()
        
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )
        
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        notification.status = NotificationStatus.READ.value
        
        db.commit()
        
        logger.info(f"✅ Notification {notification_id} marked as read")
        
        return {"message": "Notification marked as read", "notification_id": notification_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error marking notification as read: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read"
        )


@router.post("/user/read-all")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark all notifications as read"""
    try:
        from ...models.notification import Notification
        
        updated_count = db.query(Notification).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        ).update({
            "is_read": True,
            "read_at": datetime.utcnow(),
            "status": NotificationStatus.READ.value
        })
        
        db.commit()
        
        logger.info(f"✅ Marked {updated_count} notifications as read for user {current_user.id}")
        
        return {"message": f"{updated_count} notifications marked as read", "count": updated_count}
        
    except Exception as e:
        logger.error(f"❌ Error marking all as read: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all notifications as read"
        )


@router.delete("/user/{notification_id}")
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a notification"""
    try:
        from ...models.notification import Notification
        
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        ).first()
        
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )
        
        db.delete(notification)
        db.commit()
        
        logger.info(f"🗑️ Notification {notification_id} deleted")
        
        return {"message": "Notification deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting notification: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete notification"
        )


# ==================== NOTIFICATION PREFERENCES ====================

@router.get("/preferences")
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user notification preferences"""
    try:
        from ...models.notification import NotificationPreference
        
        preferences = db.query(NotificationPreference).filter(
            NotificationPreference.user_id == current_user.id
        ).first()
        
        if not preferences:
            preferences = NotificationPreference(user_id=current_user.id)
            db.add(preferences)
            db.commit()
            db.refresh(preferences)
        
        return {
            "in_app_enabled": preferences.in_app_enabled,
            "email_enabled": preferences.email_enabled,
            "sms_enabled": preferences.sms_enabled,
            "system_notifications": preferences.system_notifications,
            "content_notifications": preferences.content_notifications,
            "recommendation_notifications": preferences.recommendation_notifications,
            "subscription_notifications": preferences.subscription_notifications,
            "download_notifications": preferences.download_notifications,
            "promotion_notifications": preferences.promotion_notifications,
            "quiet_hours_enabled": preferences.quiet_hours_enabled,
            "quiet_hours_start": preferences.quiet_hours_start,
            "quiet_hours_end": preferences.quiet_hours_end
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching preferences: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch preferences"
        )


@router.put("/preferences")
async def update_notification_preferences(
    preferences_update: UserNotificationPreferences,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user notification preferences"""
    try:
        from ...models.notification import NotificationPreference
        
        preferences = db.query(NotificationPreference).filter(
            NotificationPreference.user_id == current_user.id
        ).first()
        
        if not preferences:
            preferences = NotificationPreference(user_id=current_user.id)
            db.add(preferences)
        
        update_data = preferences_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(preferences, field, value)
        
        preferences.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"✅ Preferences updated for user {current_user.id}")
        
        return {"message": "Preferences updated successfully"}
        
    except Exception as e:
        logger.error(f"❌ Error updating preferences: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update preferences"
        )


# ==================== ADMIN ENDPOINTS ====================

@router.post("/admin/send", status_code=status.HTTP_201_CREATED)
async def send_notification_admin(
    notification_data: NotificationCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """
    Send notification (Admin only)
    
    Supports in-app, email, and SMS delivery
    
    **Admin Endpoint**
    """
    try:
        from ...models.notification import Notification
        
        # Determine target users
        target_user_ids = []
        
        if notification_data.all_users:
            users = db.query(User.id).filter(User.is_active == True).all()
            target_user_ids = [u.id for u in users]
            
        elif notification_data.user_ids:
            target_user_ids = notification_data.user_ids
            
        elif notification_data.segment:
            # User segmentation
            query = db.query(User.id).filter(User.is_active == True)
            if notification_data.segment == "premium":
                query = query.filter(User.subscription_plan.in_(['premium', 'pro']))
            elif notification_data.segment == "free":
                query = query.filter(or_(User.subscription_plan == 'free', User.subscription_plan.is_(None)))
            users = query.all()
            target_user_ids = [u.id for u in users]
        
        if not target_user_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No target users specified"
            )
        
        notifications_created = []
        
        # Create notifications for each user
        for user_id in target_user_ids:
            notification = Notification(
                user_id=user_id,
                title=notification_data.title,
                body=notification_data.body,
                type=notification_data.type.value,
                priority=notification_data.priority.value,
                channels=[ch.value for ch in notification_data.channels],
                display_type=notification_data.display_type.value,
                image_url=notification_data.image_url,
                action_url=notification_data.action_url,
                action_label=notification_data.action_label,
                data=notification_data.data,
                status=NotificationStatus.PENDING.value,
                scheduled_at=notification_data.scheduled_at,
                expires_at=notification_data.expires_at,
                auto_hide_delay=notification_data.auto_hide_delay
            )
            
            db.add(notification)
            notifications_created.append(notification)
        
        db.commit()
        
        # Send notifications in background
        if not notification_data.scheduled_at:
            for notification in notifications_created:
                background_tasks.add_task(
                    send_notification_task,
                    notification.id,
                    db
                )
        
        logger.info(f"✅ {len(notifications_created)} notifications created by admin {current_user.id}")
        
        return {
            "message": f"{len(notifications_created)} notifications created",
            "count": len(notifications_created),
            "scheduled": notification_data.scheduled_at is not None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error sending notification: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send notification: {str(e)}"
        )


@router.get("/admin/list")
async def get_all_notifications_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    type: Optional[NotificationType] = None,
    status: Optional[NotificationStatus] = None,
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """Get all notifications (Admin only)"""
    try:
        from ...models.notification import Notification
        
        query = db.query(Notification)
        
        if type:
            query = query.filter(Notification.type == type.value)
        
        if status:
            query = query.filter(Notification.status == status.value)
        
        total = query.count()
        skip = (page - 1) * page_size
        notifications = query.order_by(desc(Notification.created_at)).offset(skip).limit(page_size).all()
        
        return {
            "notifications": notifications,
            "total": total,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching notifications: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch notifications"
        )


@router.get("/admin/stats")
async def get_notification_stats_admin(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """Get notification statistics (Admin only)"""
    try:
        from ...models.notification import Notification
        
        since = datetime.utcnow() - timedelta(days=days)
        
        total_sent = db.query(func.count(Notification.id)).filter(
            Notification.created_at >= since,
            Notification.status != NotificationStatus.PENDING.value
        ).scalar() or 0
        
        total_delivered = db.query(func.count(Notification.id)).filter(
            Notification.created_at >= since,
            Notification.status == NotificationStatus.DELIVERED.value
        ).scalar() or 0
        
        total_read = db.query(func.count(Notification.id)).filter(
            Notification.created_at >= since,
            Notification.is_read == True
        ).scalar() or 0
        
        total_failed = db.query(func.count(Notification.id)).filter(
            Notification.created_at >= since,
            Notification.status == NotificationStatus.FAILED.value
        ).scalar() or 0
        
        delivery_rate = (total_delivered / total_sent * 100) if total_sent > 0 else 0
        read_rate = (total_read / total_delivered * 100) if total_delivered > 0 else 0
        
        return {
            "total_sent": total_sent,
            "total_delivered": total_delivered,
            "total_read": total_read,
            "total_failed": total_failed,
            "delivery_rate": round(delivery_rate, 2),
            "read_rate": round(read_rate, 2),
            "period_days": days
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch statistics"
        )


@router.delete("/admin/{notification_id}")
async def delete_notification_admin(
    notification_id: int,
    current_user: User = Depends(get_current_superuser),
    db: Session = Depends(get_db)
):
    """Delete notification (Admin only)"""
    try:
        from ...models.notification import Notification
        
        notification = db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )
        
        db.delete(notification)
        db.commit()
        
        logger.info(f"🗑️ Admin {current_user.id} deleted notification {notification_id}")
        
        return {"message": "Notification deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting notification: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete notification"
        )


# ==================== BACKGROUND TASKS ====================

async def send_notification_task(notification_id: int, db: Session):
    """Background task to send notification via all channels"""
    try:
        from ...models.notification import Notification
        
        notification = db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if not notification:
            logger.error(f"❌ Notification {notification_id} not found")
            return
        
        service = NotificationService(db)
        success = False
        
        # Send via all channels
        for channel in notification.channels:
            if channel == NotificationChannel.IN_APP.value:
                # In-app notifications are handled by the app itself
                # Just mark as delivered
                success = True
                logger.info(f"✅ In-app notification {notification_id} ready for delivery")
            
            elif channel == NotificationChannel.EMAIL.value:
                user = db.query(User).filter(User.id == notification.user_id).first()
                if user and user.email:
                    html_body = create_notification_email_html(
                        title=notification.title,
                        body=notification.body,
                        image_url=notification.image_url,
                        action_url=notification.action_url,
                        action_label=notification.action_label or "View in Zentrya"
                    )
                    
                    sent = await service.send_email_notification(
                        email=user.email,
                        subject=notification.title,
                        body=notification.body,
                        html_body=html_body
                    )
                    if sent:
                        success = True
            
            elif channel == NotificationChannel.SMS.value:
                user = db.query(User).filter(User.id == notification.user_id).first()
                if user and user.phone:
                    sent = await service.send_sms_notification(
                        phone=user.phone,
                        message=f"{notification.title}: {notification.body}"
                    )
                    if sent:
                        success = True
        
        # Update notification status
        notification.status = NotificationStatus.DELIVERED.value if success else NotificationStatus.FAILED.value
        notification.sent_at = datetime.utcnow()
        notification.delivered_at = datetime.utcnow() if success else None
        
        db.commit()
        
        logger.info(f"✅ Notification {notification_id} sent successfully")
        
    except Exception as e:
        logger.error(f"❌ Error in send_notification_task: {str(e)}")
        
        try:
            notification.status = NotificationStatus.FAILED.value
            db.commit()
        except:
            pass


# ==================== DATABASE MODELS (for reference) ====================
"""

"""