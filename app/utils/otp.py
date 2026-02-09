# app/utils/otp.py
import random
import string
import smtplib
import aiohttp
import asyncio
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import logging

from ..config import settings

logger = logging.getLogger(__name__)

# Thread pool for blocking I/O operations (email sending)
OTP_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="otp_worker")

# ============================================================
# OTP Generation
# ============================================================

def generate_otp(length: int = 6) -> str:
    """Generate a random 6-digit OTP (pure CPU, no async needed)"""
    return ''.join(random.choices(string.digits, k=length))


# ============================================================
# Email Sending (Async with Thread Pool)
# ============================================================

def _send_email_sync(email: str, otp: str) -> bool:
    """
    Internal synchronous email sending function.
    Runs in thread pool to not block async loop.
    """
    try:
        # Email configuration
        smtp_host = settings.SMTP_HOST or "smtp.gmail.com"
        smtp_port = settings.SMTP_PORT or 587
        smtp_user = settings.SMTP_USER
        smtp_password = settings.SMTP_PASSWORD
        from_email = settings.SMTP_FROM_EMAIL or smtp_user
        
        if not smtp_user or not smtp_password:
            logger.error("❌ SMTP credentials not configured")
            raise Exception("SMTP not configured")
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Your Zentrya Sign-In Code'
        msg['From'] = formataddr(("Zentrya", from_email))
        msg['To'] = email
        
        # HTML email body
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="max-width: 500px; margin: 0 auto; background-color: #000; padding: 30px; border-radius: 10px; color: #fff;">
                    <h2 style="color: #D4A017; text-align: center; margin-bottom: 20px;">ZENTRYA</h2>
                    
                    <p style="font-size: 14px; color: #999; text-align: center; margin-bottom: 30px;">
                        Sign-In Code
                    </p>
                    
                    <div style="background-color: #1A1A1A; padding: 20px; border-radius: 8px; margin-bottom: 30px; text-align: center;">
                        <p style="font-size: 12px; color: #999; margin-bottom: 10px;">Your code:</p>
                        <p style="font-size: 36px; font-weight: bold; color: #D4A017; letter-spacing: 5px; margin: 0;">
                            {otp}
                        </p>
                    </div>
                    
                    <p style="font-size: 14px; color: #999; margin-bottom: 10px;">
                        This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.
                    </p>
                    
                    <p style="font-size: 12px; color: #777; margin-bottom: 20px;">
                        If you didn't request this code, please ignore this email.
                    </p>
                    
                    <hr style="border: none; border-top: 1px solid #333; margin: 20px 0;">
                    
                    <p style="font-size: 12px; color: #777; text-align: center;">
                        © 2026 Zentrya. All rights reserved.
                    </p>
                </div>
            </body>
        </html>
        """
        
        # Plain text version
        text_body = f"Your Zentrya Sign-In Code: {otp}\n\nThis code will expire in {settings.OTP_EXPIRY_MINUTES} minutes."
        
        part1 = MIMEText(text_body, 'plain')
        part2 = MIMEText(html_body, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email with timeout
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"✅ OTP email sent to: {email}")
        return True
        
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error sending to {email}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"❌ Failed to send OTP email to {email}: {str(e)}")
        raise


async def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email asynchronously.
    Non-blocking - runs email sending in thread pool.
    
    Usage:
        await send_otp_email("user@example.com", "123456")
    """
    try:
        loop = asyncio.get_event_loop()
        
        # Run blocking SMTP in thread pool
        result = await loop.run_in_executor(
            OTP_EXECUTOR,
            _send_email_sync,
            email,
            otp
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Async email send failed: {str(e)}")
        raise


# ============================================================
# SMS Sending (Fully Async with aiohttp)
# ============================================================

async def send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP to user's phone using Beem Africa API (async).
    Fully non-blocking with aiohttp.
    
    Usage:
        await send_otp_sms("+255712345678", "123456")
    """
    try:
        api_key = settings.BEEM_API_KEY
        api_secret = settings.BEEM_API_SECRET
        sender_id = settings.BEEM_SENDER_ID or "Zentrya"

        if not api_key or not api_secret:
            logger.error("❌ Beem Africa credentials not configured")
            raise Exception("Beem Africa not configured")

        # Generate auth header (Basic Base64)
        auth_string = f"{api_key}:{api_secret}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        url = "https://apisms.beem.africa/v1/send"
        message = f"Your Zentrya verification code is {otp}. Valid for {settings.OTP_EXPIRY_MINUTES} minutes. Do not share this code."

        payload = {
            "source_addr": sender_id,
            "schedule_time": "",
            "encoding": 0,
            "message": message,
            "recipients": [
                {
                    "recipient_id": "1",
                    "dest_addr": phone
                }
            ]
        }

        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json"
        }

        # Use aiohttp for async HTTP request
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()
                
                logger.info(f"✅ OTP SMS sent to {phone}: {result}")
                return True

    except aiohttp.ClientError as e:
        logger.error(f"❌ HTTP error sending SMS to {phone}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"❌ Failed to send OTP SMS to {phone}: {str(e)}")
        raise


# ============================================================
# Combined OTP Sending (Email + SMS)
# ============================================================

async def send_otp_both(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    otp: str = None
) -> dict:
    """
    Send OTP via both email and SMS concurrently.
    Non-blocking - both send at the same time.
    
    Usage:
        result = await send_otp_both(
            email="user@example.com",
            phone="+255712345678",
            otp="123456"
        )
    
    Returns:
        {
            "email_sent": True/False,
            "sms_sent": True/False,
            "errors": []
        }
    """
    if not otp:
        otp = generate_otp()
    
    results = {
        "otp": otp,
        "email_sent": False,
        "sms_sent": False,
        "errors": []
    }
    
    tasks = []
    
    # Prepare async tasks
    if email:
        tasks.append(("email", send_otp_email(email, otp)))
    
    if phone:
        tasks.append(("sms", send_otp_sms(phone, otp)))
    
    # Send both concurrently
    if tasks:
        task_results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True
        )
        
        # Process results
        for i, (channel, _) in enumerate(tasks):
            result = task_results[i]
            
            if isinstance(result, Exception):
                results["errors"].append({
                    "channel": channel,
                    "error": str(result)
                })
                logger.error(f"❌ Failed to send OTP via {channel}: {result}")
            else:
                if channel == "email":
                    results["email_sent"] = True
                elif channel == "sms":
                    results["sms_sent"] = True
    
    return results


# ============================================================
# Bulk OTP Sending (for multiple users)
# ============================================================

async def send_bulk_otp_emails(recipients: list[dict]) -> list[dict]:
    """
    Send OTP to multiple users concurrently.
    
    Usage:
        results = await send_bulk_otp_emails([
            {"email": "user1@example.com", "otp": "123456"},
            {"email": "user2@example.com", "otp": "654321"},
        ])
    
    Returns:
        [
            {"email": "user1@example.com", "success": True},
            {"email": "user2@example.com", "success": False, "error": "..."}
        ]
    """
    async def send_one(recipient: dict):
        try:
            await send_otp_email(recipient["email"], recipient["otp"])
            return {
                "email": recipient["email"],
                "success": True
            }
        except Exception as e:
            return {
                "email": recipient["email"],
                "success": False,
                "error": str(e)
            }
    
    # Send all concurrently
    tasks = [send_one(recipient) for recipient in recipients]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    
    return results


# ============================================================
# Cleanup on Shutdown
# ============================================================

def cleanup_otp_service():
    """Cleanup thread pool on shutdown"""
    OTP_EXECUTOR.shutdown(wait=True)
    logger.info("✅ OTP service thread pool cleaned up")


# ============================================================
# Export
# ============================================================

__all__ = [
    'generate_otp',
    'send_otp_email',
    'send_otp_sms',
    'send_otp_both',
    'send_bulk_otp_emails',
    'cleanup_otp_service',
]