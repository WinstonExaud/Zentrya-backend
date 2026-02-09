import os
from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    # 🎯 Application
    APP_NAME: str = "Zentrya API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False  # ⚠️ CRITICAL: Must be False in production
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ADMIN_TOKEN_EXPIRE_MINUTES: int = 480
    
    # 🔑 Refresh Token
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # 🌐 Server
    HOST: str = '0.0.0.0'
    PORT: int = 8000
    
    # 🗄️ Database - PostgreSQL
    DATABASE_URL: str  # ⚠️ Remove default, must come from env
    DB_ECHO: bool = False
    
    # 🔴 Redis
    REDIS_URL: str  # ⚠️ Remove default, must come from env
    REDIS_CACHE_EXPIRATION: int = 3600
    
    # 🔒 CORS
    ALLOWED_ORIGINS: str  # ⚠️ Remove default, must come from env with production domains
    
    # 📦 File Storage Configuration
    STORAGE_TYPE: str = 'hybrid'
    UPLOAD_DIR: str = '/var/www/zentrya/uploads'  # ⚠️ Use absolute production path
    MAX_FILE_SIZE: int = 5368709120  # 5GB
    
    # ☁️ Cloudflare R2 Configuration
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: Optional[str] = "zentrya-media"
    R2_PUBLIC_URL: Optional[str] = "https://media.zentrya.africa"
    R2_ENDPOINT: Optional[str] = None
    
    # 🔥 Firebase Configuration
    FIREBASE_CREDENTIALS_PATH: Optional[str] = "/var/www/zentrya/zentrya-app-firebase.json"  # ⚠️ Absolute path
    FIREBASE_STORAGE_BUCKET: Optional[str] = "zentrya-app.firebasestorage.app"
    FIREBASE_PROJECT_ID: Optional[str] = "zentrya-app"
    
    # 📧 Email Configuration (SMTP)
    SMTP_HOST: Optional[str] = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    
    # 📱 SMS Configuration (Beem Africa)
    BEEM_API_KEY: Optional[str] = None
    BEEM_API_SECRET: Optional[str] = None
    BEEM_SENDER_ID: str = "Zentrya Go"
    
    # 💳 Payment Configuration
    SELCOM_API_KEY: str | None = None
    SELCOM_API_SECRET: str | None = None
    SELCOM_VENDOR_ID: str | None = None
    SELCOM_BASE_URL: str = "https://apigw.selcommobile.com:8443/v1"  # ⚠️ Remove test URL
    
    AZAMPAY_APP_NAME: str = "Zentrya"
    AZAMPAY_CLIENT_ID: str
    AZAMPAY_CLIENT_SECRET: str
    AZAMPAY_X_API_KEY: Optional[str] = None
    AZAMPAY_ENVIRONMENT: str = "production"  # ⚠️ Change from sandbox
    
    # 🔐 Admin Account
    FIRST_SUPERUSER_EMAIL: Optional[str] = None
    FIRST_SUPERUSER_PASSWORD: Optional[str] = None
    
    # 📱 OTP Configuration
    OTP_LENGTH: int = 6
    OTP_EXPIRY_MINUTES: int = 15
    OTP_MAX_ATTEMPTS: int = 5
    
    # 🔐 Password Policy
    MIN_PASSWORD_LENGTH: int = 8
    REQUIRE_UPPERCASE: bool = True
    REQUIRE_NUMBERS: bool = True
    REQUIRE_SPECIAL_CHARS: bool = True
    
    # 🔐 Security Headers
    SECURE_COOKIES: bool = True  # ⚠️ NEW: Force HTTPS cookies
    HTTPS_ONLY: bool = True  # ⚠️ NEW: Force HTTPS
    
    # 📊 Logging
    LOG_LEVEL: str = "INFO"  # ⚠️ NEW: Production logging
    SENTRY_DSN: Optional[str] = None  # ⚠️ NEW: Error tracking

    class Config:
        env_file = ".env"
        extra = 'ignore'
    
    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse ALLOWED_ORIGINS string into list"""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(',')]
    
    @property
    def r2_endpoint_url(self) -> Optional[str]:
        """Construct R2 endpoint URL from account ID"""
        if self.R2_ACCOUNT_ID:
            return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        return self.R2_ENDPOINT
    
    @property
    def is_r2_enabled(self) -> bool:
        """Check if Cloudflare R2 is enabled"""
        return bool(
            self.R2_ACCOUNT_ID
            and self.R2_ACCESS_KEY_ID
            and self.R2_SECRET_ACCESS_KEY
            and self.R2_BUCKET_NAME
        )
    
    @property
    def is_firebase_enabled(self) -> bool:
        """Check if Firebase Storage is enabled"""
        return bool(
            self.FIREBASE_STORAGE_BUCKET
            and self.FIREBASE_CREDENTIALS_PATH
            and os.path.exists(self.FIREBASE_CREDENTIALS_PATH)
        )
    
    @property
    def is_email_enabled(self) -> bool:
        """Check if email is configured"""
        return bool(self.SMTP_HOST and self.SMTP_USER and self.SMTP_PASSWORD)
    
    @property
    def is_sms_enabled(self) -> bool:
        """Check if SMS is configured"""
        return bool(self.BEEM_API_KEY and self.BEEM_API_SECRET)

settings = Settings()