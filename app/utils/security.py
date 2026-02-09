# app/utils/security.py
from datetime import datetime, timedelta
from typing import Any, Optional
from jose import jwt, JWTError, ExpiredSignatureError
from passlib.context import CryptContext
from passlib.exc import UnknownHashError
import re
import logging
from ..config import settings

logger = logging.getLogger(__name__)

# Initialize with argon2 (no 72-byte limit, more secure)
pwd_context = CryptContext(
    schemes=['argon2'],
    deprecated='auto'
)

# ============================================================
# JWT Functions - NON-EXPIRING TOKEN SUPPORT
# ============================================================

def create_access_token_no_expiry(
    subject: Any,
    role: Optional[str] = None
) -> str:
    """
    Create a JWT access token that NEVER expires.
    Token persistence is managed entirely by AsyncStorage on the frontend.
    Server will validate token signature but not expiration.
    
    ✅ Use this for mobile/web apps with AsyncStorage session management.
    
    Args:
        subject: User ID or identifier
        role: User role (admin or client)
    
    Returns:
        JWT token string WITHOUT expiration claim
    """
    to_encode = {
        'sub': str(subject),
        'type': 'access',
        'iat': datetime.utcnow(),  # Issued at (for tracking only)
        'role': role or 'client',
        'persistent': True  # Flag to indicate this is a non-expiring token
        # ✅ NO "exp" claim - token never expires on backend
    }
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    logger.info(f"🔑 Non-expiring token created for user: {subject} (role: {role})")
    return encoded_jwt


def create_access_token(
    subject: Any,
    expires_delta: Optional[timedelta] = None,
    role: Optional[str] = None
) -> str:
    """
    Create a new JWT access token with role support and expiration.
    
    ⚠️ This creates tokens that EXPIRE. Use create_access_token_no_expiry() 
    for AsyncStorage-managed sessions.
    
    Args:
        subject: User ID or identifier
        expires_delta: Custom expiration time
        role: User role (admin or client)
    
    Returns:
        JWT token string with expiration
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        'exp': expire,
        'sub': str(subject),
        'type': 'access',
        'iat': datetime.utcnow(),
        'role': role or 'client',
        'persistent': False
    }
    
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str, ignore_expiry: bool = False) -> dict:
    """
    Decode and validate JWT token.
    
    ✅ Modified to support non-expiring tokens from create_access_token_no_expiry()
    
    Args:
        token: JWT token string
        ignore_expiry: If True, ignore expiration (for non-expiring tokens)
    
    Returns:
        Token payload dictionary
    
    Raises:
        ExpiredSignatureError: If token has expired (and ignore_expiry=False)
        JWTError: If token is invalid
    """
    try:
        # First decode without verification to check if it's a persistent token
        unverified_payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_signature": False, "verify_exp": False}
        )
        
        # Check if this is a non-expiring token
        is_persistent = unverified_payload.get('persistent', False)
        
        # If persistent token or explicitly ignoring expiry, don't verify expiration
        if is_persistent or ignore_expiry:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False}  # Don't verify expiration
            )
            logger.debug(f"✅ Non-expiring token validated for user: {payload.get('sub')}")
        else:
            # Regular token with expiration check
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )
        
        return payload
        
    except ExpiredSignatureError:
        logger.warning("Token has expired")
        raise ExpiredSignatureError("Token has expired")
    except JWTError as e:
        logger.error(f"Invalid token: {e}")
        raise JWTError(f"Invalid token: {e}")


def get_user_id_from_token(token: str) -> Optional[int]:
    """
    Extract user ID from token (supports both expiring and non-expiring tokens)
    
    Args:
        token: JWT token
        
    Returns:
        User ID or None if invalid
    """
    try:
        # Always ignore expiry when just extracting user ID
        payload = decode_access_token(token, ignore_expiry=True)
        user_id = payload.get("sub")
        return int(user_id) if user_id else None
    except Exception as e:
        logger.error(f"Error extracting user ID from token: {str(e)}")
        return None


def get_role_from_token(token: str) -> Optional[str]:
    """
    Extract user role from token (supports both expiring and non-expiring tokens)
    
    Args:
        token: JWT token
        
    Returns:
        User role or None if invalid
    """
    try:
        # Always ignore expiry when just extracting role
        payload = decode_access_token(token, ignore_expiry=True)
        return payload.get("role")
    except Exception as e:
        logger.error(f"Error extracting role from token: {str(e)}")
        return None


def is_token_persistent(token: str) -> bool:
    """
    Check if a token is a non-expiring persistent token
    
    Args:
        token: JWT token
        
    Returns:
        True if token is persistent (non-expiring)
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_signature": False, "verify_exp": False}
        )
        return payload.get('persistent', False)
    except Exception as e:
        logger.error(f"Error checking token persistence: {str(e)}")
        return False


# ============================================================
# Password Functions
# ============================================================

def get_password_hash(password: str) -> str:
    """
    Hash password with argon2
    
    Args:
        password: Plain text password
    
    Returns:
        Hashed password
    
    Raises:
        ValueError: If password is invalid
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Password hashing failed: {e}")
        raise ValueError(f"Password hashing failed: {e}")


# Alias for compatibility
hash_password = get_password_hash


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against hash with proper error handling
    
    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database
    
    Returns:
        True if password matches, False otherwise
    """
    if not plain_password or not hashed_password:
        return False
    
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except UnknownHashError:
        logger.warning("Hash format is not recognized")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during password verification: {e}")
        return False


# ============================================================
# Password Validation
# ============================================================

def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength based on policy
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, message)
    """
    min_length = getattr(settings, 'MIN_PASSWORD_LENGTH', 8)
    require_uppercase = getattr(settings, 'REQUIRE_UPPERCASE', True)
    require_numbers = getattr(settings, 'REQUIRE_NUMBERS', True)
    require_special = getattr(settings, 'REQUIRE_SPECIAL_CHARS', True)
    
    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters long"
    
    if require_uppercase and not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if require_numbers and not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    return True, "Password is strong"


# ============================================================
# Email & Phone Validation
# ============================================================

def validate_email(email: str) -> bool:
    """
    Validate email format
    
    Args:
        email: Email address
        
    Returns:
        True if valid email format
    """
    email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    return bool(re.match(email_regex, email))


def validate_phone(phone: str) -> bool:
    """
    Validate phone number format (E.164)
    
    Args:
        phone: Phone number
        
    Returns:
        True if valid phone format
    """
    phone_regex = r'^\+?[1-9]\d{1,14}$'
    return bool(re.match(phone_regex, phone))


def is_email_or_phone(value: str) -> str:
    """
    Determine if value is email or phone
    
    Args:
        value: Email or phone string
        
    Returns:
        'email', 'phone', or 'invalid'
    """
    if validate_email(value):
        return 'email'
    elif validate_phone(value):
        return 'phone'
    else:
        return 'invalid'


# ============================================================
# Token Revocation Support (Optional - for enhanced security)
# ============================================================

def create_token_with_jti(
    subject: Any,
    role: Optional[str] = None
) -> tuple[str, str]:
    """
    Create a non-expiring token with a unique JTI (JWT ID) for revocation tracking.
    
    Optional: Use this if you want to implement server-side token revocation
    in the future (store JTI in Redis/DB and check on each request).
    
    Args:
        subject: User ID
        role: User role
    
    Returns:
        Tuple of (token, jti)
    """
    import uuid
    jti = str(uuid.uuid4())
    
    to_encode = {
        'sub': str(subject),
        'type': 'access',
        'iat': datetime.utcnow(),
        'role': role or 'client',
        'persistent': True,
        'jti': jti  # Unique token ID for revocation
    }
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    logger.info(f"🔑 Non-expiring token with JTI created for user: {subject}")
    return encoded_jwt, jti