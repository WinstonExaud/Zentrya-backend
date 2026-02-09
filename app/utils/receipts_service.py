"""
Receipt Service - Send payment receipts via SMS and Email
"""

import logging
from datetime import datetime
from typing import Optional
from ..models.user import User, PaymentIntent
from .notifications import send_email, send_sms
from ..config import settings

logger = logging.getLogger(__name__)


async def send_payment_receipt(
    user: User,
    payment_intent: PaymentIntent,
    avatar_url: Optional[str] = None
):
    """
    Send payment receipt via SMS and Email
    
    Args:
        user: User object
        payment_intent: PaymentIntent object with payment details
        avatar_url: Optional avatar URL for email
    """
    
    # Format dates
    payment_date = payment_intent.created_at.strftime("%d %B %Y, %I:%M %p")
    next_billing_date = None
    subscription_end_date = None
    
    if user.auto_renew and user.next_billing_date:
        next_billing_date = user.next_billing_date.strftime("%d %B %Y")
    elif user.subscription_end_date:
        subscription_end_date = user.subscription_end_date.strftime("%d %B %Y")
    
    # Plan name formatting
    plan_name = payment_intent.subscription_plan.capitalize()
    
    # Payment provider formatting
    provider_names = {
        'airtel': 'Airtel Money',
        'mpesa': 'M-Pesa (Vodacom)',
        'halopesa': 'HaloPesa',
        'tigopesa': 'Tigo Pesa'
    }
    payment_method = provider_names.get(payment_intent.payment_provider.lower(), payment_intent.payment_provider)
    
    # ==================== SMS RECEIPT ====================
    try:
        if user.phone:
            sms_message = f"""
🎬 ZENTRYA Payment Receipt

Order ID: {payment_intent.order_id}
Amount: TZS {payment_intent.amount:,.0f}
Plan: {plan_name}
Payment: {payment_method}
Date: {payment_date}

{"Next Billing: " + next_billing_date if next_billing_date else "Valid Until: " + subscription_end_date if subscription_end_date else ""}

Thank you for choosing Zentrya!
🇹🇿 The Future of Entertainment in Tanzania

Questions? Call +255-769-123-456
            """.strip()
            
            send_sms(
                to_phone=user.phone,
                message=sms_message
            )
            
            logger.info(f"✅ SMS receipt sent to {user.phone}")
    except Exception as e:
        logger.error(f"❌ Failed to send SMS receipt: {e}")
    
    # ==================== EMAIL RECEIPT ====================
    try:
        if user.email:
            email_html = f"""



    
    
    Payment Receipt - Zentrya


    
        
        
        
            
                ZENTRYA
            
            
                🇹🇿 The Future of Entertainment in Tanzania
            
        
        
        
        
            
                ✓ Payment Successful
            
        
        
        
        
            Payment Receipt
            
            
                
                    Order ID
                    {payment_intent.order_id}
                
                
                    Payment Reference
                    {payment_intent.payment_reference}
                
                
                    Amount Paid
                    TZS {payment_intent.amount:,.0f}
                
                
                    Subscription Plan
                    {plan_name}
                
                
                    Payment Method
                    {payment_method}
                
                
                    Payment Date
                    {payment_date}
                
                {"Next Billing Date" + next_billing_date + "" if next_billing_date else ""}
                {"Subscription Valid Until" + subscription_end_date + "" if subscription_end_date else ""}
                
                    Auto-Renewal
                    {"Enabled" if user.auto_renew else "Disabled"}
                
            
            
            
            
                Customer Information
                Name: {user.full_name}
                Phone: {user.phone}
                {f'Email: {user.email}' if user.email else ''}
            
            
            
            
                
                    Important: This is your official payment receipt. Keep it for your records. 
                    {"Your subscription will automatically renew on " + next_billing_date + "." if next_billing_date else "Your subscription is valid until " + subscription_end_date + "." if subscription_end_date else ""}
                
            
            
            
            
                
                    Start Watching Now →
                
            
        
        
        
        
            
                Questions? Contact us at support@zentrya.com or call +255-769-123-456
            
            
                © 2025 Zentrya. All rights reserved.
                Arusha, Tanzania
            
        
        
    


            """.strip()
            
            send_email(
                to_email=user.email,
                subject=f"Payment Receipt - Order #{payment_intent.order_id}",
                html_content=email_html
            )
            
            logger.info(f"✅ Email receipt sent to {user.email}")
    except Exception as e:
        logger.error(f"❌ Failed to send email receipt: {e}")


# Helper function to send plain text email (if HTML fails)
def send_text_email_receipt(user: User, payment_intent: PaymentIntent):
    """Fallback text-only email receipt"""
    
    payment_date = payment_intent.created_at.strftime("%d %B %Y, %I:%M %p")
    next_billing_date = user.next_billing_date.strftime("%d %B %Y") if user.next_billing_date else None
    subscription_end_date = user.subscription_end_date.strftime("%d %B %Y") if user.subscription_end_date else None
    
    text_content = f"""
ZENTRYA Payment Receipt
========================

Payment Successful! ✓

Order ID: {payment_intent.order_id}
Payment Reference: {payment_intent.payment_reference}
Amount Paid: TZS {payment_intent.amount:,.0f}
Subscription Plan: {payment_intent.subscription_plan.capitalize()}
Payment Method: {payment_intent.payment_provider}
Payment Date: {payment_date}

{"Next Billing Date: " + next_billing_date if next_billing_date else "Valid Until: " + subscription_end_date if subscription_end_date else ""}
Auto-Renewal: {"Enabled" if user.auto_renew else "Disabled"}

Customer Information:
Name: {user.full_name}
Phone: {user.phone}
{"Email: " + user.email if user.email else ""}

Thank you for choosing Zentrya!

Start watching now: https://zentrya.com/browse

Questions? Contact us:
Email: support@zentrya.com
Phone: +255-769-123-456

--
🇹🇿 The Future of Entertainment in Tanzania
© 2025 Zentrya. All rights reserved.
    """.strip()
    
    send_email(
        to_email=user.email,
        subject=f"Payment Receipt - Order #{payment_intent.order_id}",
        text_content=text_content
    )