# app/utils/notifications.py
"""
Async notification utilities for sending emails and SMS (via Beem Africa)
📍 Location: app/utils/notifications.py

FEATURES:
- Fully async/non-blocking
- Handles concurrent requests
- Mobile-responsive email templates
- Bilingual support (English & Swahili)
"""

import logging
import smtplib
import aiohttp
import asyncio
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from ..config import settings

logger = logging.getLogger(__name__)

# Thread pool for blocking SMTP operations
NOTIFICATION_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="notification_worker")

# ============================================================
# EMAIL FUNCTIONS (ASYNC)
# ============================================================

def _send_email_sync(to_email: str, subject: str, html_content: str) -> bool:
    """
    Internal synchronous email sending (runs in thread pool)
    """
    try:
        smtp_host = settings.SMTP_HOST or 'smtp.gmail.com'
        smtp_port = settings.SMTP_PORT or 587
        smtp_user = settings.SMTP_USER
        smtp_password = settings.SMTP_PASSWORD
        from_email = settings.SMTP_FROM_EMAIL or smtp_user

        if not smtp_user or not smtp_password:
            logger.error("❌ SMTP credentials not configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr(("Zentrya", from_email))
        msg["To"] = to_email
        
        # Add plain text version for email clients that don't support HTML
        text_content = html_content.replace('<br>', '\n').replace('</p>', '\n')
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        logger.info(f"✅ Email sent to: {to_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send email to {to_email}: {str(e)}")
        return False


async def send_email(to_email: str, subject: str, html_content: str) -> bool:
    """
    Async email sender - non-blocking
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            NOTIFICATION_EXECUTOR,
            _send_email_sync,
            to_email,
            subject,
            html_content
        )
        return result
    except Exception as e:
        logger.error(f"❌ Async email send failed: {str(e)}")
        return False


# ============================================================
# MOBILE-RESPONSIVE EMAIL TEMPLATE
# ============================================================

def get_email_template(content: str, preview_text: str = "") -> str:
    """
    Stunning, professional, mobile-responsive email template for Zentrya
    Premium design with elegant spacing and professional aesthetics
    """
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="X-UA-Compatible" content="IE=edge">
        <title>Zentrya</title>
        <!--[if mso]>
        <style type="text/css">
            body, table, td {{font-family: Arial, sans-serif !important;}}
        </style>
        <![endif]-->
    </head>
    <body style="margin:0;padding:0;background-color:#f5f5f5;font-family:'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
        <!-- Preview text -->
        <div style="display:none;font-size:1px;color:#f5f5f5;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
            {preview_text}
        </div>
        
        <!-- Outer Container -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:0;padding:0;background-color:#f5f5f5;">
            <tr>
                <td style="padding:40px 20px;">
                    <!-- Main Email Card -->
                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width:640px;margin:0 auto;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
                        
                        <!-- Header with Gradient -->
                        <tr>
                            <td style="padding:0;background:linear-gradient(135deg, #1a1a1a 0%, #333333 100%);position:relative;">
                                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                    <tr>
                                        <td style="padding:50px 40px;text-align:center;">
                                            <h1 style="margin:0;color:#ffffff;font-size:42px;font-weight:700;letter-spacing:2px;text-transform:uppercase;">ZENTRYA</h1>
                                            <div style="width:60px;height:3px;background-color:#ffffff;margin:20px auto;opacity:0.3;"></div>
                                            <p style="margin:0;color:#cccccc;font-size:15px;letter-spacing:1px;text-transform:uppercase;">Your World Of African Stories</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        
                        <!-- Content Area -->
                        <tr>
                            <td style="padding:50px 40px;">
                                {content}
                            </td>
                        </tr>
                        
                        <!-- Divider -->
                        <tr>
                            <td style="padding:0 40px;">
                                <div style="height:1px;background:linear-gradient(90deg, transparent, #e0e0e0, transparent);"></div>
                            </td>
                        </tr>
                        
                        <!-- Footer -->
                        <tr>
                            <td style="padding:40px;background-color:#fafafa;">
                                <!-- Support Section -->
                                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                    <tr>
                                        <td style="text-align:center;padding-bottom:25px;">
                                            <p style="margin:0 0 8px;color:#666666;font-size:14px;line-height:1.6;">
                                                Need assistance? We're here to help
                                            </p>
                                            <a href="mailto:support@zentrya.africa" style="color:#1a1a1a;text-decoration:none;font-weight:600;font-size:15px;letter-spacing:0.5px;">info@zentrya.africa</a>
                                        </td>
                                    </tr>
                                </table>
                                
                                <!-- Separator Line -->
                                <div style="height:1px;background-color:#e0e0e0;margin:25px 0;"></div>
                                
                                <!-- Company Info -->
                                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                    <tr>
                                        <td style="text-align:center;">
                                            <p style="margin:0 0 5px;color:#999999;font-size:13px;line-height:1.8;">
                                                Zentrya Limited
                                            </p>
                                            <p style="margin:0 0 5px;color:#999999;font-size:13px;line-height:1.8;">
                                                Arusha, Tanzania
                                            </p>
                                            <p style="margin:15px 0 0;color:#bbbbbb;font-size:12px;line-height:1.6;">
                                                © 2026 Zentrya. All rights reserved.
                                            </p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        
                    </table>
                    
                    <!-- Spacer for mobile -->
                    <div style="height:20px;"></div>
                    
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


async def send_welcome_email(to_email: str, full_name: str, trial_end_date: datetime) -> bool:
    """
    Send stunning professional welcome email for free trial signup
    """
    trial_end_str = trial_end_date.strftime('%B %d, %Y')
    
    content = f"""
        <!-- Personal Greeting -->
        <h2 style="margin:0 0 16px;color:#1a1a1a;font-size:28px;font-weight:600;line-height:1.3;">
            Welcome, {full_name}
        </h2>
        
        <p style="margin:0 0 30px;color:#555555;font-size:17px;line-height:1.7;">
            Thank you for joining <strong style="color:#1a1a1a;">Zentrya</strong>, Tanzania's premier platform for authentic local films, series, and storytelling.
        </p>
        
        <!-- Trial Activation Box -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:35px 0;background-color:#f8f8f8;border-radius:8px;overflow:hidden;">
            <tr>
                <td style="padding:30px;border-left:4px solid #1a1a1a;">
                    <p style="margin:0 0 12px;color:#1a1a1a;font-size:18px;font-weight:600;letter-spacing:0.3px;">
                        Your 30-Day Free Trial is Active
                    </p>
                    <p style="margin:0;color:#666666;font-size:15px;line-height:1.6;">
                        Full platform access until <strong style="color:#1a1a1a;">{trial_end_str}</strong><br>
                        <span style="color:#888888;font-size:14px;">No payment required during your trial period</span>
                    </p>
                </td>
            </tr>
        </table>
        
        <!-- Features Section -->
        <h3 style="margin:40px 0 24px;color:#1a1a1a;font-size:20px;font-weight:600;letter-spacing:0.3px;">
            Your Access Includes
        </h3>
        
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
            <tr>
                <td style="padding:16px 0;border-bottom:1px solid #f0f0f0;">
                    <p style="margin:0;color:#1a1a1a;font-size:16px;font-weight:600;line-height:1.5;">
                        Unlimited Streaming
                    </p>
                    <p style="margin:6px 0 0;color:#666666;font-size:14px;line-height:1.6;">
                        Access our complete library of Tanzanian movies and series
                    </p>
                </td>
            </tr>
            <tr>
                <td style="padding:16px 0;border-bottom:1px solid #f0f0f0;">
                    <p style="margin:0;color:#1a1a1a;font-size:16px;font-weight:600;line-height:1.5;">
                        Support Local Creators
                    </p>
                    <p style="margin:6px 0 0;color:#666666;font-size:14px;line-height:1.6;">
                        Every view directly supports Tanzanian filmmakers
                    </p>
                </td>
            </tr>
            <tr>
                <td style="padding:16px 0;">
                    <p style="margin:0;color:#1a1a1a;font-size:16px;font-weight:600;line-height:1.5;">
                        Beta Program Benefits
                    </p>
                    <p style="margin:6px 0 0;color:#666666;font-size:14px;line-height:1.6;">
                        Early access to new features and exclusive content
                    </p>
                </td>
            </tr>
        </table>
        
        <!-- Divider -->
        <div style="height:1px;background:linear-gradient(90deg, transparent, #e0e0e0, transparent);margin:40px 0;"></div>
        
        <!-- Swahili Section -->
        <h3 style="margin:0 0 20px;color:#1a1a1a;font-size:20px;font-weight:600;letter-spacing:0.3px;">
            Kwa Kiswahili
        </h3>
        
        <p style="margin:0 0 30px;color:#555555;font-size:15px;line-height:1.7;">
            <strong style="color:#1a1a1a;">Zentrya</strong> ni jukwaa la kisasa la kutazama filamu na mipango ya Kitanzania. Kama mtumiaji wa awali, unasaidia kuendeleza tasnia ya filamu nchini na kupata fursa ya kuona maudhui mapya kabla ya wengine.
        </p>
        
        <!-- Beta Notice -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:35px 0;background-color:#f8f8f8;border-radius:8px;overflow:hidden;">
            <tr>
                <td style="padding:30px;border-left:4px solid #1a1a1a;">
                    <p style="margin:0 0 12px;color:#1a1a1a;font-size:18px;font-weight:600;letter-spacing:0.3px;">
                        Beta Platform
                    </p>
                    <p style="margin:0;color:#666666;font-size:15px;line-height:1.6;">
                        Zentrya is currently in beta. New features and content are added regularly. As an early member, you'll have priority access to all updates.
                    </p>
                </td>
            </tr>
        </table>
        
        <!-- CTA Button -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:45px 0 20px;">
            <tr>
                <td style="text-align:center;">
                    <a href="https://zentrya.africa/app" style="display:inline-block;background-color:#1a1a1a;color:#ffffff;text-decoration:none;padding:16px 48px;border-radius:6px;font-weight:600;font-size:16px;letter-spacing:0.5px;box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:all 0.3s ease;">
                        Start Watching Now
                    </a>
                </td>
            </tr>
        </table>
        
        <p style="margin:30px 0 0;text-align:center;color:#888888;font-size:14px;line-height:1.6;">
            Access Zentrya on any device — desktop, mobile, or tablet
        </p>
    """
    
    subject = "Welcome to Zentrya — Your Account is Ready"
    preview_text = f"Welcome {full_name}! Your 30-day free trial is now active. Start exploring Tanzanian cinema today."
    
    html_content = get_email_template(content, preview_text)
    return await send_email(to_email, subject, html_content)


# ============================================================
# SMS FUNCTIONS (FULLY ASYNC with aiohttp)
# ============================================================

def _normalize_phone(phone: str) -> str:
    """Ensure phone numbers are in +255XXXXXXXXX format"""
    phone = phone.strip()
    if phone.startswith("+"):
        return phone
    if phone.startswith("255"):
        return f"+{phone}"
    if phone.startswith("0"):
        return f"+255{phone[1:]}"
    return f"+255{phone}"


async def send_sms(phone: str, message: str, sender_id: str = "Zentrya Go") -> bool:
    """
    Async SMS sender using Beem Africa API
    Fully non-blocking with aiohttp
    """
    try:
        api_key = settings.BEEM_API_KEY
        api_secret = settings.BEEM_API_SECRET
        
        if not api_key or not api_secret:
            logger.error("❌ Beem Africa credentials missing")
            return False

        phone = _normalize_phone(phone)

        # Remove emojis / special characters for SMS compatibility
        plain_message = message.encode("ascii", errors="ignore").decode()

        # Prepare auth header
        auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        url = "https://apisms.beem.africa/v1/send"

        payload = {
            "source_addr": sender_id,
            "schedule_time": "",
            "encoding": 0,
            "message": plain_message,
            "recipients": [{"recipient_id": "1", "dest_addr": phone}]
        }

        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json"
        }

        # Async HTTP request
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()
                
                logger.info(f"✅ SMS sent to {phone}")
                return True

    except aiohttp.ClientError as e:
        logger.error(f"❌ Beem API error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send SMS: {str(e)}")
        return False


# ============================================================
# WELCOME SMS (BILINGUAL)
# ============================================================

async def send_welcome_sms(to_phone: str, full_name: str, trial_end_date: datetime) -> bool:
    """
    Send welcome SMS for free trial signup (async)
    """
    message = (
        "Welcome to Zentrya | Karibu Zentrya! "
        "Your account is ready. Start watching Tanzanian films and shows. "
        "Enjoy your 30-day free trial!"
    )
    return await send_sms(to_phone, message)


# ============================================================
# WAITLIST NOTIFICATIONS
# ============================================================

async def send_waitlist_welcome_sms(to_phone: str, position: int) -> bool:
    """Send welcome SMS when user joins waitlist (async)"""
    message = (
        f"ZENTRYA: Welcome to the waitlist! You're #{position}. "
        "We'll notify you at launch with exclusive early access. Stay tuned!"
    )
    return await send_sms(to_phone, message)


async def send_launch_notification_sms(to_phone: str) -> bool:
    """Send launch notification SMS (async)"""
    message = (
        "ZENTRYA IS LIVE! As an early supporter, get 20% OFF your first 3 months. "
        "Sign up now at zentrya.africa. Limited time offer!"
    )
    return await send_sms(to_phone, message)


# ============================================================
# COMBINED NOTIFICATIONS (EMAIL + SMS)
# ============================================================

async def send_welcome_notification(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    full_name: str = "",
    trial_end_date: datetime = None
) -> dict:
    """
    Send welcome notification via both email and SMS concurrently
    
    Returns:
        {
            "email_sent": bool,
            "sms_sent": bool,
            "errors": []
        }
    """
    results = {
        "email_sent": False,
        "sms_sent": False,
        "errors": []
    }
    
    tasks = []
    
    if email:
        tasks.append(("email", send_welcome_email(email, full_name, trial_end_date)))
    
    if phone:
        tasks.append(("sms", send_welcome_sms(phone, full_name, trial_end_date)))
    
    if tasks:
        task_results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True
        )
        
        for i, (channel, _) in enumerate(tasks):
            result = task_results[i]
            
            if isinstance(result, Exception):
                results["errors"].append({
                    "channel": channel,
                    "error": str(result)
                })
            else:
                if channel == "email":
                    results["email_sent"] = result
                elif channel == "sms":
                    results["sms_sent"] = result
    
    return results


# ============================================================
# BULK NOTIFICATIONS
# ============================================================

async def send_bulk_emails(recipients: list[dict]) -> list[dict]:
    """
    Send emails to multiple recipients concurrently
    
    Args:
        recipients: [{"email": "...", "subject": "...", "content": "..."}]
    
    Returns:
        [{"email": "...", "success": bool, "error": "..."}]
    """
    async def send_one(recipient: dict):
        try:
            success = await send_email(
                recipient["email"],
                recipient["subject"],
                recipient["content"]
            )
            return {
                "email": recipient["email"],
                "success": success
            }
        except Exception as e:
            return {
                "email": recipient["email"],
                "success": False,
                "error": str(e)
            }
    
    tasks = [send_one(r) for r in recipients]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    
    return results


# ============================================================
# CLEANUP
# ============================================================

def cleanup_notification_service():
    """Cleanup thread pool on shutdown"""
    NOTIFICATION_EXECUTOR.shutdown(wait=True)
    logger.info("✅ Notification service cleaned up")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    'send_email',
    'send_sms',
    'send_welcome_email',
    'send_welcome_sms',
    'send_welcome_notification',
    'send_waitlist_welcome_sms',
    'send_launch_notification_sms',
    'send_bulk_emails',
    'cleanup_notification_service',
]