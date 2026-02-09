"""
Waitlist API endpoints for Zentrya Coming Soon page
📍 Location: app/api/routes/waitlist.py

Handles waitlist subscriptions with email/SMS notifications
Admin can manage and notify waitlist subscribers
"""

import logging
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from ...database import get_db
from ...models.waitlist import Waitlist, WaitlistStatus
from ...utils.notifications import (
    send_email, 
    send_sms,
    send_waitlist_welcome_sms,      # ← ADD
    send_launch_notification_sms     # ← ADD
)
from ...utils.security import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter()

# ==================== AUTHENTICATION DEPENDENCY ====================

async def get_current_admin_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """
    Dependency to get current admin user from token
    Validates that user is admin or superuser
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        # Extract token from "Bearer <token>"
        scheme, _, token = authorization.partition(" ")
        
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token not provided",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Decode token (supports non-expiring tokens)
        payload = decode_access_token(token, ignore_expiry=True)
        user_id = payload.get("sub")
        role = payload.get("role")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Import User model here to avoid circular imports
        from ...models.user import User, UserRole
        
        # Get user from database
        user = db.query(User).filter(User.id == int(user_id)).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated"
            )
        
        # Verify user is admin or superuser
        if user.role != UserRole.ADMIN and not user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        logger.info(f"✅ Admin authenticated: {user.email} (ID: {user.id})")
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Authentication error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )

# ==================== REQUEST/RESPONSE MODELS ====================

class JoinWaitlistRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v:
            # Validate Tanzanian phone format
            clean = re.sub(r'[^\d+]', '', v)
            if not re.match(r'^\+255[67]\d{8}$', clean):
                raise ValueError('Invalid Tanzanian phone number. Must be +255XXXXXXXXX')
        return v

    @model_validator(mode='after')
    def check_at_least_one_contact(self):
        """Ensure at least one contact method is provided"""
        if not self.email and not self.phone:
            raise ValueError('Either email or phone is required')
        return self



class WaitlistResponse(BaseModel):
    id: int
    email: Optional[str]
    phone: Optional[str]
    status: str
    position: int
    joined_at: datetime
    message: str


class NotifyWaitlistRequest(BaseModel):
    subject: str
    message: str
    send_email: bool = True
    send_sms: bool = True


# ==================== HELPER FUNCTIONS ====================

def normalize_phone(phone: str) -> str:
    """Normalize phone number to +255XXXXXXXXX format"""
    if not phone:
        return ''
    
    clean = re.sub(r'[^\d+]', '', phone)
    
    # Auto-add +255 if starts with 0
    if clean.startswith('0'):
        clean = '+255' + clean[1:]
    # Ensure +255 prefix
    elif clean.startswith('255'):
        clean = '+' + clean
    elif not clean.startswith('+'):
        clean = '+255' + clean
    
    return clean


def send_waitlist_welcome_email(to_email: str, position: int) -> bool:
    """Send welcome email when user joins waitlist"""
    subject = "🎉 You're on the Zentrya Waitlist!"
    
    html_content = f"""
    <html>
    <body style="background-color:#000;color:#fff;font-family:Arial,sans-serif;padding:30px;margin:0;">
        <div style="max-width:650px;margin:0 auto;background-color:#0a0a0a;border:2px solid #D4A017;border-radius:20px;padding:40px;">
            
            <!-- Header -->
            <div style="text-align:center;margin-bottom:30px;">
                <h1 style="color:#D4A017;font-size:42px;font-weight:900;margin:0;letter-spacing:2px;">ZENTRYA</h1>
                <p style="color:#888;font-size:14px;margin:5px 0;">The Future of Entertainment in Tanzania 🇹🇿</p>
            </div>
            
            <!-- Success Badge -->
            <div style="text-align:center;margin-bottom:30px;">
                <div style="display:inline-block;background-color:#2e7d32;color:#fff;padding:15px 30px;border-radius:50px;font-size:18px;font-weight:bold;">
                    ✅ You're on the Waitlist!
                </div>
            </div>
            
            <hr style="border:none;border-top:1px solid #333;margin:30px 0;">
            
            <h2 style="color:#D4A017;font-size:24px;margin-bottom:20px;">Welcome to Zentrya!</h2>
            
            <p style="color:#ccc;font-size:16px;line-height:1.6;">
                Thank you for joining our exclusive waitlist! You're one of the first to experience the next generation of African entertainment.
            </p>
            
            <!-- Position Card -->
            <div style="background-color:#1a1a1a;padding:20px;border-radius:10px;margin:25px 0;text-align:center;">
                <p style="color:#888;margin:0 0 10px 0;font-size:14px;">Your Position</p>
                <p style="color:#D4A017;font-size:48px;font-weight:bold;margin:0;">#{position}</p>
            </div>
            
            <!-- What's Coming -->
            <div style="background-color:#1a1a1a;border-left:4px solid #D4A017;padding:20px;margin:25px 0;border-radius:5px;">
                <h3 style="color:#D4A017;margin:0 0 15px 0;font-size:18px;">🎬 What to Expect</h3>
                <ul style="color:#ccc;padding-left:20px;margin:0;line-height:1.8;">
                    <li>Exclusive Tanzanian and East African content</li>
                    <li>Premium Zentrya Originals</li>
                    <li>4K streaming quality</li>
                    <li>Offline downloads</li>
                    <li>Multi-device support</li>
                    <li>Early access pricing</li>
                </ul>
            </div>
            
            <!-- Benefits Box -->
            <div style="background-color:#1a3a1a;border-left:4px solid #4CAF50;padding:15px;margin:25px 0;border-radius:5px;">
                <p style="color:#4CAF50;font-weight:bold;margin:0 0 10px 0;">🎁 Early Bird Benefits</p>
                <p style="color:#ccc;margin:0;font-size:14px;">
                    • Priority access at launch<br>
                    • Exclusive launch day offers<br>
                    • Be the first to watch new releases
                </p>
            </div>
            
            <p style="color:#aaa;font-size:14px;line-height:1.6;margin-top:25px;">
                We'll keep you updated on our launch progress. Get ready for an amazing entertainment experience!
            </p>
            
            <!-- Social Media -->
            <hr style="border:none;border-top:1px solid #333;margin:35px 0;">
            
            <div style="text-align:center;">
                <p style="color:#888;font-size:14px;margin-bottom:15px;">Follow us for updates</p>
                <div style="margin:10px 0;">
                    <a href="#" style="color:#D4A017;text-decoration:none;margin:0 10px;">Facebook</a>
                    <span style="color:#333;">|</span>
                    <a href="#" style="color:#D4A017;text-decoration:none;margin:0 10px;">Twitter</a>
                    <span style="color:#333;">|</span>
                    <a href="#" style="color:#D4A017;text-decoration:none;margin:0 10px;">Instagram</a>
                </div>
            </div>
            
            <!-- Support -->
            <hr style="border:none;border-top:1px solid #333;margin:35px 0;">
            
            <div style="text-align:center;">
                <p style="color:#888;font-size:13px;margin:5px 0;">
                    Questions? Contact us at 
                    <a href="mailto:support@zentrya.com" style="color:#D4A017;text-decoration:none;">support@zentrya.com</a>
                </p>
            </div>
            
            <!-- Footer -->
            <hr style="border:none;border-top:1px solid #333;margin:35px 0;">
            
            <p style="font-size:11px;text-align:center;color:#666;line-height:1.6;">
                You're receiving this because you joined the Zentrya waitlist.<br><br>
                © 2025 Zentrya. All rights reserved.<br>
                Dar es Salaam, Tanzania 🇹🇿
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, html_content)


def send_launch_notification_email(to_email: str) -> bool:
    """Send launch notification email to waitlist subscribers"""
    subject = "🚀 Zentrya is LIVE! Your Early Access is Ready"
    
    html_content = """
    <html>
    <body style="background-color:#000;color:#fff;font-family:Arial,sans-serif;padding:30px;">
        <div style="max-width:650px;margin:0 auto;background-color:#0a0a0a;border:2px solid #D4A017;border-radius:20px;padding:40px;">
            
            <div style="text-align:center;margin-bottom:30px;">
                <h1 style="color:#D4A017;font-size:42px;font-weight:900;margin:0;">ZENTRYA</h1>
                <p style="color:#888;font-size:14px;margin:5px 0;">The Future of Entertainment in Tanzania 🇹🇿</p>
            </div>
            
            <div style="text-align:center;margin-bottom:30px;">
                <div style="display:inline-block;background-color:#2e7d32;color:#fff;padding:20px 40px;border-radius:50px;font-size:24px;font-weight:bold;">
                    🚀 WE'RE LIVE!
                </div>
            </div>
            
            <hr style="border:none;border-top:1px solid #333;margin:30px 0;">
            
            <h2 style="color:#D4A017;font-size:28px;text-align:center;margin-bottom:20px;">
                Zentrya Has Launched!
            </h2>
            
            <p style="color:#ccc;font-size:18px;line-height:1.8;text-align:center;">
                The wait is over! As a valued waitlist member, you now have <b style="color:#D4A017;">exclusive early access</b> to Zentrya's premium African entertainment platform.
            </p>
            
            <div style="background-color:#1a3a1a;border-left:4px solid #4CAF50;padding:20px;margin:30px 0;border-radius:5px;">
                <h3 style="color:#4CAF50;margin:0 0 15px 0;">🎁 Your Early Bird Benefits</h3>
                <ul style="color:#ccc;margin:0;padding-left:20px;line-height:1.8;">
                    <li><b>20% OFF</b> your first 3 months</li>
                    <li>Exclusive access to Zentrya Originals</li>
                    <li>Priority customer support</li>
                    <li>Free trial extended to 14 days</li>
                </ul>
            </div>
            
            <div style="text-align:center;margin:40px 0;">
                <a href="https://zentrya.com/signup" style="display:inline-block;background:linear-gradient(135deg, #D4A017, #f0c419);color:#000;text-decoration:none;padding:20px 50px;border-radius:30px;font-weight:bold;font-size:18px;box-shadow:0 4px 15px rgba(212,160,23,0.4);">
                    Start Watching Now →
                </a>
            </div>
            
            <p style="color:#aaa;font-size:14px;text-align:center;margin-top:30px;">
                Thank you for being an early supporter of Zentrya!<br>
                We can't wait for you to experience our platform.
            </p>
            
            <hr style="border:none;border-top:1px solid #333;margin:35px 0;">
            
            <p style="font-size:11px;text-align:center;color:#666;">
                © 2025 Zentrya. All rights reserved.<br>
                Dar es Salaam, Tanzania 🇹🇿
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, html_content)


# ==================== PUBLIC ENDPOINTS ====================

@router.post("/join", response_model=WaitlistResponse)
async def join_waitlist(
    request: JoinWaitlistRequest,
    db: Session = Depends(get_db)
):
    """
    Join the Zentrya waitlist
    - Accepts email OR phone (or both)
    - Sends welcome email/SMS immediately
    - Returns position in waitlist
    """
    try:
        email = request.email.lower() if request.email else None
        phone = normalize_phone(request.phone) if request.phone else None
        
        logger.info(f"📝 Waitlist join request - Email: {email}, Phone: {phone}")
        
        # Check if already on waitlist - FIXED VERSION
        existing_query = db.query(Waitlist)
        
        # Build the filter conditions properly to avoid None matches
        conditions = []
        if email:
            conditions.append(Waitlist.email == email)
        if phone:
            conditions.append(Waitlist.phone == phone)
        
        # Only check if we have at least one condition
        if conditions:
            existing = existing_query.filter(or_(*conditions)).first()
        else:
            existing = None
        
        if existing:
            logger.info(f"⚠️ Already on waitlist: {existing.id}")
            return WaitlistResponse(
                id=existing.id,
                email=existing.email,
                phone=existing.phone,
                status=existing.status.value,
                position=existing.position,
                joined_at=existing.joined_at,
                message="You're already on our waitlist! We'll notify you at launch."
            )
        
        # Get next position
        max_position = db.query(Waitlist).count()
        next_position = max_position + 1
        
        # Create waitlist entry
        waitlist_entry = Waitlist(
            email=email,
            phone=phone,
            status=WaitlistStatus.PENDING,
            position=next_position,
            joined_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        
        db.add(waitlist_entry)
        db.commit()
        db.refresh(waitlist_entry)
        
        logger.info(f"✅ Added to waitlist: {waitlist_entry.id} at position {next_position}")
        
        # Send welcome email
        if email:
            try:
                logger.info(f"📧 Sending welcome email to: {email}")
                send_waitlist_welcome_email(email, next_position)
            except Exception as e:
                logger.error(f"❌ Failed to send welcome email: {e}")
        
        # Send welcome SMS
        if phone:
            try:
                logger.info(f"📱 Sending welcome SMS to: {phone}")
                await send_waitlist_welcome_sms(phone, next_position) 
            except Exception as e:
                logger.error(f"❌ Failed to send welcome SMS: {e}")
        
        return WaitlistResponse(
            id=waitlist_entry.id,
            email=waitlist_entry.email,
            phone=waitlist_entry.phone,
            status=waitlist_entry.status.value,
            position=next_position,
            joined_at=waitlist_entry.joined_at,
            message="Welcome to the waitlist! Check your email/phone for confirmation."
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Waitlist join failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join waitlist: {str(e)}"
        )


# ==================== ADMIN ENDPOINTS ====================

@router.get("/admin/list")
async def list_waitlist(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    Admin: List all waitlist entries
    - Supports pagination
    - Filter by status
    """
    query = db.query(Waitlist).order_by(Waitlist.position)
    
    if status_filter:
        try:
            status_enum = WaitlistStatus(status_filter)
            query = query.filter(Waitlist.status == status_enum)
        except ValueError:
            pass
    
    total = query.count()
    entries = query.offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "entries": [
            {
                "id": entry.id,
                "email": entry.email,
                "phone": entry.phone,
                "status": entry.status.value,
                "position": entry.position,
                "joined_at": entry.joined_at,
                "notified_at": entry.notified_at
            }
            for entry in entries
        ]
    }


@router.get("/admin/stats")
async def waitlist_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    Admin: Get waitlist statistics
    """
    total = db.query(Waitlist).count()
    pending = db.query(Waitlist).filter(Waitlist.status == WaitlistStatus.PENDING).count()
    notified = db.query(Waitlist).filter(Waitlist.status == WaitlistStatus.NOTIFIED).count()
    
    return {
        "total": total,
        "pending": pending,
        "notified": notified,
        "with_email": db.query(Waitlist).filter(Waitlist.email.isnot(None)).count(),
        "with_phone": db.query(Waitlist).filter(Waitlist.phone.isnot(None)).count()
    }


@router.post("/admin/notify-all")
async def notify_all_waitlist(
    request: NotifyWaitlistRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    Admin: Notify all pending waitlist members
    - Sends launch notification via email/SMS
    - Marks as notified
    """
    logger.info(f"📢 Admin {current_user.email} initiating waitlist notification")
    
    # Get all pending entries
    entries = db.query(Waitlist).filter(
        Waitlist.status == WaitlistStatus.PENDING
    ).all()
    
    success_count = 0
    error_count = 0
    
    for entry in entries:
        try:
            # Send email
            if entry.email and request.send_email:
                send_launch_notification_email(entry.email)
            
            # Send SMS
            if entry.phone and request.send_sms:
                send_launch_notification_sms(entry.phone)
            
            # Mark as notified
            entry.status = WaitlistStatus.NOTIFIED
            entry.notified_at = datetime.utcnow()
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"❌ Failed to notify {entry.id}: {e}")
            error_count += 1
    
    db.commit()
    
    logger.info(f"✅ Notified {success_count} waitlist members, {error_count} errors")
    
    return {
        "message": f"Notification sent to {success_count} members",
        "success": success_count,
        "errors": error_count,
        "total": len(entries)
    }


@router.delete("/admin/{waitlist_id}")
async def delete_waitlist_entry(
    waitlist_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin_user)
):
    """
    Admin: Delete a waitlist entry
    """
    entry = db.query(Waitlist).filter(Waitlist.id == waitlist_id).first()
    
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Waitlist entry not found"
        )
    
    db.delete(entry)
    db.commit()
    
    return {"message": "Waitlist entry deleted successfully"}