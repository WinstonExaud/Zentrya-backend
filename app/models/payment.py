"""
ZENTRYA Payment Model
Complete payment transaction tracking with Selcom integration
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum as SQLEnum, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from enum import Enum
from ..database import Base


# ==================== ENUMS ====================

class PaymentStatus(str, Enum):
    """Payment transaction status"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PaymentProvider(str, Enum):
    """Payment provider options"""
    SELCOM = "selcom"
    MPESA = "mpesa"
    TIGOPESA = "tigopesa"
    AIRTEL_MONEY = "airtel_money"
    HALOPESA = "halopesa"
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"


class BillingCycle(str, Enum):
    """Subscription billing cycle"""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


# ==================== PAYMENT MODEL ====================

class Payment(Base):
    """
    Payment transactions table
    Tracks all payments including subscriptions, renewals, and one-time purchases
    """
    __tablename__ = "payments"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # User Reference
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Transaction Identification
    transaction_id = Column(String(255), unique=True, index=True, nullable=False)  # Selcom transaction ID
    order_id = Column(String(255), unique=True, index=True, nullable=False)  # Our order ID (ZEN-XXXX)
    
    # Payment Amount
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default='TZS', nullable=False)
    
    # Payment Method Details
    payment_provider = Column(SQLEnum(PaymentProvider, name="payment_provider_type"), default=PaymentProvider.SELCOM, nullable=False, index=True)
    payment_method = Column(String(50), nullable=True)  # mpesa, tigopesa, airtel, card
    payment_phone = Column(String(20), nullable=True, index=True)  # Phone number used for mobile money
    payment_email = Column(String(255), nullable=True)  # Email for card payments
    
    # Payment Status
    status = Column(SQLEnum(PaymentStatus, name="payment_status_type"), default=PaymentStatus.PENDING, index=True, nullable=False)
    
    # Subscription Details
    subscription_plan = Column(String(100), nullable=True)  # mobile, basic, standard, premium
    billing_cycle = Column(SQLEnum(BillingCycle, name="billing_cycle_type"), nullable=True)  # monthly, quarterly, yearly
    is_renewal = Column(Boolean, default=False)  # Is this an auto-renewal?
    
    # Selcom/Provider Specific Fields
    reference = Column(String(255), nullable=True, index=True)  # Selcom payment reference
    result_code = Column(String(50), nullable=True)  # Provider result code
    result_description = Column(Text, nullable=True)  # Provider response description
    provider_response = Column(Text, nullable=True)  # Full JSON response from provider
    
    # Receipt Details
    receipt_number = Column(String(100), unique=True, index=True, nullable=True)  # Generated receipt number
    receipt_sent = Column(Boolean, default=False)  # Receipt email/SMS sent?
    receipt_sent_at = Column(DateTime(timezone=True), nullable=True)
    
    # Additional Metadata
    description = Column(Text, nullable=True)  # Payment description/notes
    customer_name = Column(String(255), nullable=True)
    
    # Refund Information
    refund_amount = Column(Float, nullable=True)
    refund_reason = Column(Text, nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    paid_at = Column(DateTime(timezone=True), nullable=True)  # When payment was confirmed
    
    # ==================== RELATIONSHIPS ====================
    
    user = relationship("User", back_populates="payments")
    
    # ==================== METHODS ====================
    
    def __repr__(self):
        return f"<Payment(id={self.id}, order_id={self.order_id}, status={self.status}, amount={self.amount})>"
    
    def is_successful(self) -> bool:
        """Check if payment was successful"""
        return self.status == PaymentStatus.SUCCESS
    
    def is_pending(self) -> bool:
        """Check if payment is pending"""
        return self.status == PaymentStatus.PENDING
    
    def is_failed(self) -> bool:
        """Check if payment failed"""
        return self.status == PaymentStatus.FAILED
    
    def mark_as_paid(self):
        """Mark payment as successful"""
        self.status = PaymentStatus.SUCCESS
        self.paid_at = datetime.utcnow()
    
    def generate_receipt_number(self) -> str:
        """Generate unique receipt number"""
        if not self.receipt_number:
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            self.receipt_number = f"REC-{timestamp}-{self.id}"
        return self.receipt_number
    
    def format_amount(self) -> str:
        """Format amount with currency"""
        return f"{self.currency} {self.amount:,.2f}"
    
    def get_payment_method_display(self) -> str:
        """Get human-readable payment method"""
        method_names = {
            'mpesa': 'M-Pesa (Vodacom)',
            'tigopesa': 'Tigo Pesa',
            'airtel': 'Airtel Money',
            'halopesa': 'HaloPesa',
            'card': 'Credit/Debit Card',
            'bank_transfer': 'Bank Transfer'
        }
        return method_names.get(self.payment_method, self.payment_method or 'Unknown')


# ==================== PAYMENT HISTORY MODEL ====================

class PaymentHistory(Base):
    """
    Payment history audit trail
    Records all payment state changes for auditing
    """
    __tablename__ = "payment_history"
    
    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Status Change
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    
    # Change Details
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # Admin who made change
    change_reason = Column(Text, nullable=True)
    
    # Metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    payment = relationship("Payment")
    
    def __repr__(self):
        return f"<PaymentHistory(payment_id={self.payment_id}, {self.old_status} -> {self.new_status})>"


# ==================== SUBSCRIPTION TRANSACTION MODEL ====================

class SubscriptionTransaction(Base):
    """
    Subscription-specific transactions
    Links payments to subscription periods
    """
    __tablename__ = "subscription_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)
    
    # Subscription Period
    subscription_plan = Column(String(100), nullable=False)
    billing_cycle = Column(SQLEnum(BillingCycle, name="billing_cycle_type_transactions"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default='TZS')
    
    # Period Dates
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Transaction Type
    is_trial = Column(Boolean, default=False)
    is_renewal = Column(Boolean, default=False)
    is_upgrade = Column(Boolean, default=False)
    is_downgrade = Column(Boolean, default=False)
    
    # Status
    status = Column(String(50), default='active', index=True)  # active, expired, canceled
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    user = relationship("User")
    payment = relationship("Payment")
    
    def __repr__(self):
        return f"<SubscriptionTransaction(user_id={self.user_id}, plan={self.subscription_plan}, status={self.status})>"
    
    def is_active(self) -> bool:
        """Check if subscription period is currently active"""
        now = datetime.utcnow()
        return self.period_start <= now <= self.period_end and self.status == 'active'
    
    def days_remaining(self) -> int:
        """Calculate days remaining in subscription period"""
        if not self.is_active():
            return 0
        delta = self.period_end - datetime.utcnow()
        return max(0, delta.days)