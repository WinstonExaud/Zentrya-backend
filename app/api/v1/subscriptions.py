"""
Subscription Management Endpoints
Router: /api/v1/subscriptions
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
import logging

from ...database import get_db
from ...models.user import User
from ...api.deps import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class SubscriptionResponse(BaseModel):
    subscription_id: Optional[int] = None
    plan_name: str
    status: str
    amount: float
    currency: str
    billing_cycle: str
    start_date: datetime
    next_billing_date: datetime
    end_date: Optional[datetime] = None
    last_four: Optional[str] = None
    payment_method: Optional[str] = None
    auto_renew: bool

class MessageResponse(BaseModel):
    message: str


# ==================== Endpoints ====================

@router.get("/active")
def get_active_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get active subscription for current user
    Returns subscription details from optimized user model (Selcom-ready)
    """
    try:
        # Check if User model has subscription fields
        if not hasattr(current_user, 'subscription_status'):
            # Return mock data for testing
            logger.warning(f"⚠️ User model missing subscription fields for user {current_user.id}")
            return {
                "subscription_status": "active",
                "subscription_plan": "Premium Plan",
                "subscription_amount": 9.99,
                "subscription_currency": "TZS",
                "subscription_start_date": datetime.utcnow().isoformat(),
                "subscription_end_date": None,
                "next_billing_date": (datetime.utcnow() + timedelta(days=30)).isoformat(),
                "payment_provider": "mpesa",
                "payment_last_four": "1234",
                "payment_reference": "SELCOM-12345",
                "auto_renew": True
            }
        
        # Return subscription data directly (not wrapped in "subscription" key)
        subscription_data = {
            # Core subscription info
            "subscription_status": str(getattr(current_user, 'subscription_status', 'inactive')),
            "subscription_plan": getattr(current_user, 'subscription_plan', None),
            "subscription_amount": getattr(current_user, 'subscription_amount', 0.0),
            "subscription_currency": getattr(current_user, 'subscription_currency', 'TZS'),
            
            # Dates (convert to ISO format if datetime object)
            "subscription_start_date": (
                current_user.subscription_start_date.isoformat() 
                if current_user.subscription_start_date else None
            ),
            "subscription_end_date": (
                current_user.subscription_end_date.isoformat() 
                if current_user.subscription_end_date else None
            ),
            "next_billing_date": (
                current_user.next_billing_date.isoformat() 
                if current_user.next_billing_date else None
            ),
            
            # Payment info (Selcom/Mobile Money)
            "payment_provider": str(getattr(current_user, 'payment_provider', None)) if getattr(current_user, 'payment_provider', None) else None,
            "payment_last_four": getattr(current_user, 'payment_last_four', None),
            "payment_reference": getattr(current_user, 'payment_reference', None),
            
            # Settings
            "auto_renew": getattr(current_user, 'auto_renew', True)
        }
        
        logger.info(f"✅ Retrieved subscription for user: {current_user.id} - Status: {subscription_data['subscription_status']}")
        
        return subscription_data
        
    except Exception as e:
        logger.error(f"❌ Failed to get subscription: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return None instead of raising error
        return {
            "subscription_status": "inactive",
            "subscription_plan": None,
            "subscription_amount": 0.0,
            "subscription_currency": "TZS",
            "subscription_start_date": None,
            "subscription_end_date": None,
            "next_billing_date": None,
            "payment_provider": None,
            "payment_last_four": None,
            "payment_reference": None,
            "auto_renew": False
        }


@router.post("/cancel", response_model=MessageResponse)
def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cancel user subscription
    Access continues until the end of the billing period
    """
    try:
        if not hasattr(current_user, 'subscription_status'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active subscription found"
            )
        
        if current_user.subscription_status != 'active':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subscription is not active"
            )
        
        # Update subscription status to canceled
        current_user.subscription_status = 'canceled'
        
        # Set auto_renew to False
        if hasattr(current_user, 'auto_renew'):
            current_user.auto_renew = False
        
        # Set end date to next billing date
        if hasattr(current_user, 'next_billing_date'):
            current_user.subscription_end_date = current_user.next_billing_date
        
        db.commit()
        
        logger.info(f"✅ Subscription canceled for user: {current_user.id}")
        
        # TODO: Send cancellation confirmation email
        # TODO: Notify payment processor (Stripe, etc.)
        
        return {
            "message": "Subscription canceled successfully. You will have access until the end of your billing period."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Subscription cancellation failed: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription"
        )


@router.post("/reactivate", response_model=MessageResponse)
def reactivate_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Reactivate a canceled subscription
    """
    try:
        if not hasattr(current_user, 'subscription_status'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No subscription found"
            )
        
        if current_user.subscription_status != 'canceled':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subscription is not canceled"
            )
        
        # Reactivate subscription
        current_user.subscription_status = 'active'
        
        if hasattr(current_user, 'auto_renew'):
            current_user.auto_renew = True
        
        if hasattr(current_user, 'subscription_end_date'):
            current_user.subscription_end_date = None
        
        db.commit()
        
        logger.info(f"✅ Subscription reactivated for user: {current_user.id}")
        
        return {"message": "Subscription reactivated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Subscription reactivation failed: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reactivate subscription"
        )


@router.get("/history")
def get_subscription_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get subscription history for current user
    """
    try:
        # TODO: Implement proper subscription history from database
        # For now, return mock data
        
        history = [
            {
                "id": 1,
                "plan_name": "Premium Plan",
                "amount": 9.99,
                "currency": "TZS",
                "billing_date": datetime.utcnow().isoformat(),
                "status": "paid",
                "invoice_url": None
            }
        ]
        
        return {"history": history, "total": len(history)}
        
    except Exception as e:
        logger.error(f"❌ Failed to get subscription history: {str(e)}")
        return {"history": [], "total": 0}