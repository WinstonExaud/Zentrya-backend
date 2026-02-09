from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel

from ...database import get_db
from ...models.user import User
from ...api.deps import get_current_user

router = APIRouter()

class PaymentHistoryResponse(BaseModel):
    id: int
    amount: float
    currency: str
    status: str
    payment_method: str
    transaction_id: str
    created_at: str

@router.get("/history/list")
def get_payment_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get payment history for current user
    Note: This returns subscription-based payments from user data.
    In production, you should have a separate Payment/Transaction table.
    """
    try:
        payments = []
        
        # If user has an active subscription, create a payment record
        if hasattr(current_user, 'subscription_status') and current_user.subscription_status == 'active':
            # Get subscription plan price
            plan_prices = {

            }
            
            plan = getattr(current_user, 'subscription_plan', 'Premium')
            amount = plan_prices.get(plan, 17.99)
            
            payments.append({
                "id": 1,
                "amount": amount,
                "currency": "TZS",
                "status": "completed",
                "payment_method": getattr(current_user, 'payment_method', 'card'),
                "transaction_id": getattr(current_user, 'order_id', 'N/A'),
                "created_at": current_user.created_at.isoformat() if current_user.created_at else datetime.utcnow().isoformat()
            })
        
        return {"payments": payments}
        
    except Exception as e:
        print(f"Error fetching payment history: {e}")
        return {"payments": []}
    

    