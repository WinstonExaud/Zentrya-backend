# app/api/endpoints/auth.py
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr, validator
from typing import Optional
import logging
import re
import asyncio

from ...database import get_async_db
from ...models.user import User, UserRole, OtpSession, UserProfile, SubscriptionStatus, UserDevice
from ...utils.security import (
    create_access_token_no_expiry,
    verify_password, 
    get_password_hash
)
from ...utils.otp import generate_otp, send_otp_email, send_otp_sms
from ...utils.notifications import send_welcome_notification
from ...config import settings

logger = logging.getLogger(__name__)

# ✅ Main router
router = APIRouter()

# ✅ Sub-routers
client_router = APIRouter(prefix="/client")
admin_router = APIRouter(prefix="/admin")

# ==================== REQUEST/RESPONSE MODELS ====================

class LoginRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "email": "user@example.com",
                "password": "your_password"
            }]
        }
    }

class SignupRequest(BaseModel):
    full_name: str
    phone: str
    email: Optional[EmailStr] = None
    password: str
    display_name: str
    avatar_icon_index: int = 0

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        if len(v) > 60:
            raise ValueError('Password must be less than 60 characters')
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        if not v:
            raise ValueError('Phone number is required')
        return v

class OtpRequest(BaseModel):
    email_or_phone: str

class OtpVerifyRequest(BaseModel):
    email_or_phone: str
    otp: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

class UserExistsResponse(BaseModel):
    exists: bool
    message: str

class SignUpResponse(BaseModel):
    message: str
    access_token: str
    token_type: str
    user: dict
    profile: dict

class ResetPasswordRequest(BaseModel):
    email_or_phone: str
    new_password: str
    
    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        if len(v) > 60:
            raise ValueError('Password must be less than 60 characters')
        return v  


# ==================== 🔧 HELPER FUNCTIONS ====================

def normalize_phone(phone: str) -> str:
    """Normalize phone number to clean format"""
    if not phone:
        return ''
    clean = re.sub(r'[^\d+]', '', phone)
    if clean.startswith('0'):
        clean = '+255' + clean[1:]
    elif clean.startswith('255'):
        clean = '+' + clean
    elif not clean.startswith('+'):
        clean = '+255' + clean
    return clean


def validate_tanzanian_phone(phone: str) -> bool:
    """Validate Tanzanian phone number"""
    clean = normalize_phone(phone)
    pattern = r'^\+255[67]\d{8}$'
    return bool(re.match(pattern, clean))


def parse_user_agent(user_agent: str) -> dict:
    """Parse user agent string to extract device information"""
    device_info = {
        "device_name": "Unknown Device",
        "device_type": "Unknown",
        "browser": None,
        "os": None
    }
    
    if not user_agent:
        return device_info
    
    user_agent_lower = user_agent.lower()
    
    # Detect device type and OS
    if "mobile" in user_agent_lower or "android" in user_agent_lower or "iphone" in user_agent_lower:
        device_info["device_type"] = "Mobile"
        if "android" in user_agent_lower:
            device_info["device_name"] = "Android Phone"
            device_info["os"] = "Android"
        elif "iphone" in user_agent_lower:
            device_info["device_name"] = "iPhone"
            device_info["os"] = "iOS"
    elif "tablet" in user_agent_lower or "ipad" in user_agent_lower:
        device_info["device_type"] = "Tablet"
        if "ipad" in user_agent_lower:
            device_info["device_name"] = "iPad"
            device_info["os"] = "iOS"
        else:
            device_info["device_name"] = "Android Tablet"
            device_info["os"] = "Android"
    elif "tv" in user_agent_lower or "smarttv" in user_agent_lower:
        device_info["device_type"] = "TV"
        device_info["device_name"] = "Smart TV"
    else:
        device_info["device_type"] = "Desktop"
        device_info["device_name"] = "Desktop Computer"
        
        if "windows" in user_agent_lower:
            device_info["os"] = "Windows"
        elif "mac" in user_agent_lower:
            device_info["os"] = "macOS"
        elif "linux" in user_agent_lower:
            device_info["os"] = "Linux"
    
    # Detect browser
    if "chrome" in user_agent_lower and "edg" not in user_agent_lower:
        device_info["browser"] = "Chrome"
    elif "firefox" in user_agent_lower:
        device_info["browser"] = "Firefox"
    elif "safari" in user_agent_lower and "chrome" not in user_agent_lower:
        device_info["browser"] = "Safari"
    elif "edg" in user_agent_lower:
        device_info["browser"] = "Edge"
    elif "opera" in user_agent_lower:
        device_info["browser"] = "Opera"
    
    if device_info["browser"] and device_info["device_type"] == "Mobile":
        device_info["device_name"] = f"{device_info['device_name']} - {device_info['browser']}"
    
    return device_info


async def register_user_device(
    user_id: int,
    user_agent: Optional[str],
    ip_address: Optional[str],
    db: AsyncSession
):
    """Register or update user device on login/signup (ASYNC)"""
    try:
        if not user_agent:
            logger.warning("⚠️ No user agent provided, skipping device registration")
            return
        
        # Parse user agent
        device_info = parse_user_agent(user_agent)
        device_name = device_info.get("device_name", "Unknown Device")
        device_type = device_info.get("device_type", "Unknown")
        browser = device_info.get("browser")
        os = device_info.get("os")
        
        # Check if device already exists
        result = await db.execute(
            select(UserDevice).where(
                and_(
                    UserDevice.user_id == user_id,
                    UserDevice.device_name == device_name
                )
            )
        )
        existing_device = result.scalar_one_or_none()
        
        if existing_device:
            # Update last_active and IP
            existing_device.last_active = datetime.utcnow()
            if ip_address:
                existing_device.ip_address = ip_address
            await db.commit()
            logger.info(f"✅ Device updated: {device_name} for user {user_id}")
        else:
            # Create new device record
            new_device = UserDevice(
                user_id=user_id,
                device_name=device_name,
                device_type=device_type,
                browser=browser,
                os=os,
                ip_address=ip_address,
                last_active=datetime.utcnow(),
                created_at=datetime.utcnow()
            )
            db.add(new_device)
            await db.commit()
            logger.info(f"✅ New device registered: {device_name} for user {user_id}")
            
    except Exception as e:
        logger.error(f"❌ Device registration failed: {str(e)}")
        await db.rollback()


# ==================== 📝 FREE TRIAL SIGNUP ====================

@client_router.post("/signup", response_model=SignUpResponse)
async def signup(
    signup_data: SignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    user_agent: Optional[str] = Header(None)
):
    """
    Free trial signup - fully async, non-blocking
    - Creates user with 30-day free trial
    - Creates default profile
    - Sends welcome notifications concurrently
    - Returns access token
    """
    try:
        logger.info(f"📝 Free trial signup for: {signup_data.email or signup_data.phone}")
        
        # 1. Validate phone number
        clean_phone = normalize_phone(signup_data.phone)
        if not validate_tanzanian_phone(clean_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Tanzanian phone number"
            )
        
        # 2. Verify phone was verified via OTP (async query)
        result = await db.execute(
            select(OtpSession).where(
                and_(
                    OtpSession.email_or_phone == clean_phone,
                    OtpSession.user_id.is_(None),
                    OtpSession.is_used == True,
                    OtpSession.verified_at.isnot(None),
                    OtpSession.verified_at > datetime.utcnow() - timedelta(hours=1)
                )
            ).order_by(OtpSession.verified_at.desc())
            .limit(1)
        )
        recent_verification = result.scalar_one_or_none()
        
        if not recent_verification:
            logger.warning(f"⚠️ No recent phone verification found for: {clean_phone}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please verify your phone number first"
            )
        
        # 3. Validate email format
        if signup_data.email:
            email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
            if not re.match(email_regex, signup_data.email):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid email format"
                )
        
        # 4. Check if user exists (async query)
        result = await db.execute(
            select(User).where(
                or_(
                    User.email == signup_data.email,
                    User.phone == clean_phone
                )
            )
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email or phone already exists"
            )
        
        # 5. Prepare user data
        avatar_icon_str = str(signup_data.avatar_icon_index)
        hashed_password = get_password_hash(signup_data.password)
        
        # 6. Calculate trial dates
        now = datetime.utcnow()
        trial_end = now + timedelta(days=30)
        
        # 7. Create user
        new_user = User(
            email=signup_data.email,
            full_name=signup_data.full_name,
            hashed_password=hashed_password,
            phone=clean_phone,
            display_name=signup_data.display_name,
            avatar_url=avatar_icon_str,
            role=UserRole.CLIENT,
            is_active=True,
            is_superuser=False,
            email_verified=bool(signup_data.email),
            phone_verified=True,
            subscription_plan="free_trial",
            subscription_status=SubscriptionStatus.ACTIVE,
            subscription_start_date=now,
            subscription_end_date=trial_end,
            next_billing_date=trial_end,
            subscription_amount=0.00,
            subscription_currency="TZS",
            auto_renew=False,
            created_at=now,
            updated_at=now,
            last_login=now
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        logger.info(f"✅ User created: {new_user.id} - {new_user.email or new_user.phone}")
        
        # 8. Create default profile
        default_profile = UserProfile(
            user_id=new_user.id,
            name=signup_data.display_name,
            avatar=avatar_icon_str,
            is_kids=False,
            is_active=True,
            language_preference="en",
            subtitle_preference=True,
            autoplay_next=True,
            created_at=now,
            updated_at=now
        )
        db.add(default_profile)
        await db.commit()
        await db.refresh(default_profile)
        
        logger.info(f"✅ Profile created: {default_profile.id}")
        
        # 9. Register device (async, non-blocking)
        device_task = register_user_device(
            user_id=new_user.id,
            user_agent=user_agent,
            ip_address=request.client.host if request.client else None,
            db=db
        )
        
        # 10. Send welcome notifications (async, non-blocking)
        notification_task = send_welcome_notification(
            email=new_user.email,
            phone=new_user.phone,
            full_name=new_user.full_name,
            trial_end_date=trial_end
        )
        
        # Run device registration and notifications concurrently
        await asyncio.gather(
            device_task,
            notification_task,
            return_exceptions=True  # Don't fail signup if notifications fail
        )
        
        # 11. Generate token
        access_token = create_access_token_no_expiry(
            subject=new_user.id,
            role=new_user.role.value
        )
        
        logger.info(f"✅ Free trial signup completed: {new_user.email or new_user.phone}")
        
        return SignUpResponse(
            message=f"Welcome to Zentrya! Your 30-day free trial has started.",
            access_token=access_token,
            token_type="bearer",
            user={
                "id": new_user.id,
                "email": new_user.email,
                "phone": new_user.phone,
                "full_name": new_user.full_name,
                "display_name": new_user.display_name,
                "avatar_url": new_user.avatar_url,
                "role": new_user.role.value,
                "is_active": new_user.is_active,
                "subscription_plan": new_user.subscription_plan,
                "subscription_status": new_user.subscription_status.value,
                "subscription_end_date": new_user.subscription_end_date.isoformat() if new_user.subscription_end_date else None,
                "trial_days_remaining": (trial_end - now).days
            },
            profile={
                "id": default_profile.id,
                "name": default_profile.name,
                "avatar": default_profile.avatar,
                "is_kids": default_profile.is_kids,
                "is_active": default_profile.is_active
            }
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Signup failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete signup: {str(e)}"
        )


# ==================== 👥 CLIENT AUTH ENDPOINTS ====================

@client_router.get("/user-exists", response_model=UserExistsResponse)
async def check_user_exists(
    email_or_phone: str,
    db: AsyncSession = Depends(get_async_db)
):
    """Check if a user exists (async)"""
    
    email_or_phone = email_or_phone.strip()
    
    if not email_or_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or phone number is required"
        )
    
    logger.info(f"🔍 Checking user existence: {email_or_phone}")
    
    # Validate format
    email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    is_email = bool(re.match(email_regex, email_or_phone))
    
    if is_email:
        result = await db.execute(
            select(User).where(User.email == email_or_phone)
        )
    else:
        clean_phone = normalize_phone(email_or_phone)
        result = await db.execute(
            select(User).where(User.phone == clean_phone)
        )
    
    user = result.scalar_one_or_none()
    
    if user:
        logger.info(f"✅ User exists: {email_or_phone}")
        return UserExistsResponse(
            exists=True,
            message="User found. You can proceed to login."
        )
    else:
        logger.info(f"❌ User not found: {email_or_phone}")
        return UserExistsResponse(
            exists=False,
            message="User not found. You can proceed with registration."
        )


@client_router.post("/login", response_model=TokenResponse)
async def client_login(
    credentials: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    user_agent: Optional[str] = Header(None)
):
    """Client login - fully async, non-blocking"""
    
    if not credentials.email and not credentials.phone:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "validation_error",
                "message": "Either email or phone is required"
            }
        )
    
    password = credentials.password
    
    # Find user (async)
    user = None
    if credentials.email:
        identifier = credentials.email.lower().strip()
        logger.info(f"🔍 Login attempt with email: {identifier}")
        result = await db.execute(
            select(User).where(User.email == identifier)
        )
        user = result.scalar_one_or_none()
    
    if not user and credentials.phone:
        clean_phone = normalize_phone(credentials.phone.strip())
        logger.info(f"🔍 Login attempt with phone: {clean_phone}")
        result = await db.execute(
            select(User).where(User.phone == clean_phone)
        )
        user = result.scalar_one_or_none()
    
    if not user:
        logger.warning(f"❌ User not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/phone or password"
        )
    
    # Verify password
    try:
        is_valid = verify_password(password, user.hashed_password)
    except Exception as e:
        logger.error(f"❌ Password verification error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/phone or password"
        )
    
    if not is_valid:
        logger.warning(f"❌ Password mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/phone or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated"
        )
    
    # Check profile (async)
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile_count = len(result.scalars().all())
    
    if profile_count == 0:
        logger.info(f"👤 Creating default profile for user: {user.id}")
        default_profile = UserProfile(
            user_id=user.id,
            name=user.display_name or user.full_name or "Main Profile",
            avatar=user.avatar_url or "0",
            is_kids=False,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(default_profile)
        await db.commit()
    
    # Register device (async)
    await register_user_device(
        user_id=user.id,
        user_agent=user_agent,
        ip_address=request.client.host if request.client else None,
        db=db
    )
    
    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()
    
    # Generate token
    access_token = create_access_token_no_expiry(
        subject=user.id,
        role=user.role.value
    )
    
    logger.info(f"✅ Login successful: {user.email or user.phone}")
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user={
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active
        }
    )


# ==================== 📱 SIGNUP OTP ENDPOINTS ====================

@client_router.post("/send-signup-otp")
async def send_signup_otp(
    request: OtpRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """Send OTP for signup verification (async)"""
    
    phone = request.email_or_phone.strip()
    
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is required"
        )
    
    clean_phone = normalize_phone(phone)
    
    if not validate_tanzanian_phone(clean_phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Tanzanian phone number"
        )
    
    logger.info(f"📱 Send SIGNUP OTP request: {clean_phone}")
    
    # Check if user exists (async)
    result = await db.execute(
        select(User).where(User.phone == clean_phone)
    )
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        logger.warning(f"⚠️ User already exists: {clean_phone}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This phone number is already registered. Please sign in instead."
        )
    
    # Generate OTP
    otp_code = generate_otp(6)
    
    # Create OTP session
    try:
        otp_session = OtpSession(
            user_id=None,
            otp_code=otp_code,
            email_or_phone=clean_phone,
            is_used=False,
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        db.add(otp_session)
        await db.commit()
        logger.info(f"✅ Signup OTP session created")
    except Exception as e:
        logger.error(f"❌ Could not create OTP session: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create OTP session"
        )
    
    # Send OTP via SMS (async, non-blocking)
    try:
        logger.info(f"📱 Sending SIGNUP OTP to phone: {clean_phone}")
        await send_otp_sms(clean_phone, otp_code)
        
        logger.info(f"✅ SIGNUP OTP sent successfully to {clean_phone}")
        return {
            "message": f"Verification code sent to {clean_phone}",
            "detail": "Please check your phone for the 6-digit code",
            "phone": clean_phone
        }
    except Exception as e:
        logger.error(f"❌ Failed to send signup OTP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification code. Please try again."
        )


@client_router.post("/verify-signup-otp")
async def verify_signup_otp(
    request_data: OtpVerifyRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """Verify OTP for signup (async)"""
    
    phone = request_data.email_or_phone.strip()
    otp_code = request_data.otp.strip()
    
    if not phone or not otp_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number and OTP are required"
        )
    
    clean_phone = normalize_phone(phone)
    
    logger.info(f"✅ SIGNUP OTP verification attempt: {clean_phone}")
    
    try:
        # Get latest OTP session (async)
        result = await db.execute(
            select(OtpSession).where(
                and_(
                    OtpSession.email_or_phone == clean_phone,
                    OtpSession.user_id.is_(None),
                    OtpSession.is_used == False,
                    OtpSession.expires_at > datetime.utcnow()
                )
            ).order_by(OtpSession.created_at.desc())
            .limit(1)
        )
        otp_session = result.scalar_one_or_none()
        
        if not otp_session:
            logger.warning(f"❌ No valid OTP session found for: {clean_phone}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OTP has expired or not found. Please request a new code."
            )
        
        if otp_session.attempts >= otp_session.max_attempts:
            logger.warning(f"❌ Too many attempts for: {clean_phone}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Too many attempts. Please request a new verification code."
            )
        
        # Increment attempts
        otp_session.attempts += 1
        
        # Verify OTP
        if otp_session.otp_code != otp_code:
            await db.commit()
            remaining = otp_session.max_attempts - otp_session.attempts
            logger.warning(f"❌ Invalid OTP. Attempts remaining: {remaining}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid verification code. {remaining} attempts remaining."
            )
        
        # Mark as used
        otp_session.is_used = True
        otp_session.verified_at = datetime.utcnow()
        await db.commit()
        
        logger.info(f"✅ SIGNUP OTP verified for: {clean_phone}")
        
        return {
            "message": "Phone number verified successfully",
            "detail": "You can now complete your signup",
            "phone": clean_phone,
            "verified": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Signup OTP verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify OTP. Please try again."
        )


# ==================== 📱 LOGIN OTP ENDPOINTS ====================

@client_router.post("/send-otp")
async def client_send_otp(
    request: OtpRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """Send OTP for login (async)"""
    
    email_or_phone = request.email_or_phone.strip()
    
    if not email_or_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or phone number is required"
        )
    
    logger.info(f"📱 Send LOGIN OTP request: {email_or_phone}")
    
    # Validate format
    email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    is_email = bool(re.match(email_regex, email_or_phone))
    
    # Find user (async)
    if is_email:
        result = await db.execute(
            select(User).where(User.email == email_or_phone)
        )
    else:
        clean_phone = normalize_phone(email_or_phone)
        result = await db.execute(
            select(User).where(User.phone == clean_phone)
        )
    
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up first."
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated"
        )
    
    # Generate OTP
    otp_code = generate_otp(6)
    
    # Create OTP session
    try:
        otp_session = OtpSession(
            user_id=user.id,
            otp_code=otp_code,
            email_or_phone=email_or_phone,
            is_used=False,
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        db.add(otp_session)
        await db.commit()
    except Exception as e:
        logger.warning(f"⚠️ Could not create OTP session: {e}")
    
    # Send OTP (async, non-blocking)
    try:
        if is_email:
            logger.info(f"📧 Sending OTP to email: {email_or_phone}")
            await send_otp_email(email_or_phone, otp_code)
        else:
            logger.info(f"📱 Sending OTP to phone: {email_or_phone}")
            await send_otp_sms(email_or_phone, otp_code)
        
        logger.info(f"✅ LOGIN OTP sent successfully")
        return {
            "message": f"OTP sent to {email_or_phone}",
            "detail": "Please check your email or phone for the code"
        }
    except Exception as e:
        logger.error(f"❌ Failed to send OTP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP. Please try again."
        )


@client_router.post("/verify-otp", response_model=TokenResponse)
async def client_verify_otp(
    request_data: OtpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    user_agent: Optional[str] = Header(None)
):
    """Verify OTP and login (async)"""
    
    email_or_phone = request_data.email_or_phone.strip()
    otp_code = request_data.otp.strip()
    
    if not email_or_phone or not otp_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email/phone and OTP are required"
        )
    
    logger.info(f"✅ OTP verification attempt: {email_or_phone}")
    
    try:
        # Get latest OTP session with EAGER LOADING for user relationship
        result = await db.execute(
            select(OtpSession)
            .options(selectinload(OtpSession.user))  # Eager load user
            .where(
                and_(
                    OtpSession.email_or_phone == email_or_phone,
                    OtpSession.is_used == False,
                    OtpSession.expires_at > datetime.utcnow()
                )
            )
            .order_by(OtpSession.created_at.desc())
            .limit(1)
        )
        otp_session = result.scalar_one_or_none()
        
        if not otp_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OTP has expired. Please request a new one."
            )
        
        if otp_session.attempts >= otp_session.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Too many attempts. Please request a new OTP."
            )
        
        # Increment attempts
        otp_session.attempts += 1
        
        # Verify OTP
        if otp_session.otp_code != otp_code:
            await db.commit()
            remaining = otp_session.max_attempts - otp_session.attempts
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid OTP. {remaining} attempts remaining."
            )
        
        # Mark as used
        otp_session.is_used = True
        otp_session.verified_at = datetime.utcnow()
        await db.commit()
        
        # Get user (already loaded via eager loading)
        user = otp_session.user
        
        if not user:
            # If user is None, this is a signup OTP, not login
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This OTP is for signup verification. Please complete signup."
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ OTP verification error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated"
        )
    
    # Check profile (async)
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profiles = result.scalars().all()
    
    if len(profiles) == 0:
        default_profile = UserProfile(
            user_id=user.id,
            name=user.display_name or user.full_name or "Main Profile",
            avatar=user.avatar_url or "0",
            is_kids=False,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(default_profile)
        await db.commit()
    
    # Register device (async)
    await register_user_device(
        user_id=user.id,
        user_agent=user_agent,
        ip_address=request.client.host if request.client else None,
        db=db
    )
    
    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()
    
    # Generate token
    access_token = create_access_token_no_expiry(
        subject=user.id,
        role=user.role.value
    )
    
    logger.info(f"✅ OTP verified: {user.email or user.phone}")
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user={
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active
        }
    )


@client_router.post("/logout")
async def client_logout():
    """Client logout"""
    logger.info("🚪 Client logout")
    return {"message": "Logged out successfully"}


@client_router.post("/reset-password")
async def client_reset_password(
    request_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """Reset password (async)"""
    
    email_or_phone = request_data.email_or_phone.strip()
    new_password = request_data.new_password
    
    if not email_or_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or phone number is required"
        )
    
    if not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password is required"
        )
    
    logger.info(f"🔒 Password reset request: {email_or_phone}")
    
    try:
        # Validate format
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        is_email = bool(re.match(email_regex, email_or_phone))
        
        # Find user (async)
        if is_email:
            result = await db.execute(
                select(User).where(User.email == email_or_phone)
            )
        else:
            clean_phone = normalize_phone(email_or_phone)
            result = await db.execute(
                select(User).where(User.phone == clean_phone)
            )
        
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has been deactivated"
            )
        
        # Verify recent OTP - GET MOST RECENT ONE with LIMIT
        result = await db.execute(
            select(OtpSession)
            .where(
                and_(
                    OtpSession.email_or_phone == email_or_phone,
                    OtpSession.user_id == user.id,
                    OtpSession.is_used == True,
                    OtpSession.verified_at.isnot(None),
                    OtpSession.verified_at > datetime.utcnow() - timedelta(minutes=30)
                )
            )
            .order_by(OtpSession.verified_at.desc())
            .limit(1)  # LIMIT to 1 row
        )
        recent_otp = result.scalar_one_or_none()  # Now safe since we limited to 1
        
        if not recent_otp:
            logger.warning(f"⚠️ No recent OTP verification found for: {email_or_phone}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please verify your OTP before resetting password"
            )
        
        # Hash new password
        hashed_password = get_password_hash(new_password)
        
        # Update password
        user.hashed_password = hashed_password
        user.updated_at = datetime.utcnow()
        
        # Invalidate all unused OTP sessions for this user
        await db.execute(
            update(OtpSession)
            .where(
                and_(
                    OtpSession.user_id == user.id,
                    OtpSession.is_used == False
                )
            )
            .values(is_used=True)
        )
        
        await db.commit()
        
        logger.info(f"✅ Password reset successful for: {user.email or user.phone}")
        
        return {
            "message": "Password reset successfully. You can now login with your new password."
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Password reset failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset password: {str(e)}"
        )


# ==================== 👨‍💼 ADMIN AUTH ENDPOINTS ====================

@admin_router.post("/login", response_model=TokenResponse)
async def admin_login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db),
    user_agent: Optional[str] = Header(None)
):
    """Admin login (async)"""
    
    email = form_data.username.lower().strip()
    password = form_data.password
    
    logger.info(f"🔍 Admin login attempt: {email}")
    
    # Find user (async)
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()
    
    is_admin = False
    if user:
        is_admin = user.role == UserRole.ADMIN or user.is_superuser
    
    if not user or not is_admin:
        logger.warning(f"❌ Admin not found or unauthorized: {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or insufficient permissions"
        )
    
    try:
        is_valid = verify_password(password, user.hashed_password)
    except Exception as e:
        logger.error(f"❌ Password verification error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your admin account has been deactivated"
        )
    
    # Register device (async)
    await register_user_device(
        user_id=user.id,
        user_agent=user_agent,
        ip_address=request.client.host if request.client else None,
        db=db
    )
    
    user.last_login = datetime.utcnow()
    await db.commit()
    
    access_token = create_access_token_no_expiry(
        subject=user.id,
        role=user.role.value
    )
    
    logger.info(f"✅ Admin login successful: {email}")
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user={
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser
        }
    )


@admin_router.post("/logout")
async def admin_logout():
    """Admin logout"""
    logger.info("🚪 Admin logout")
    return {"message": "Logged out successfully"}


# ==================== INCLUDE SUB-ROUTERS ====================

router.include_router(client_router, tags=["auth-client"])
router.include_router(admin_router, tags=["auth-admin"])