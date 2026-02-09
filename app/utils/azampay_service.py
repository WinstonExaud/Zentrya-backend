import httpx
import json
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
import logging

from ..config import settings

logger = logging.getLogger(__name__)

class AzamPayService:
    """
    AzamPay Payment Gateway Service
    Supports: M-Pesa, Tigo Pesa, Airtel Money, HaloPesa, AzamPesa
    """
    
    def __init__(self):
        self.app_name = settings.AZAMPAY_APP_NAME
        self.client_id = settings.AZAMPAY_CLIENT_ID
        self.client_secret = settings.AZAMPAY_CLIENT_SECRET
        self.x_api_key = settings.AZAMPAY_X_API_KEY
        
        # Set URLs based on environment
        if settings.AZAMPAY_ENVIRONMENT == "sandbox":
            self.auth_url = "https://authenticator-sandbox.azampay.co.tz"
            self.base_url = "https://sandbox.azampay.co.tz"
        else:
            self.auth_url = "https://authenticator.azampay.co.tz"
            self.base_url = "https://checkout.azampay.co.tz"
        
        self.access_token = None
        self.token_expiry = None
    
    async def authenticate(self) -> bool:
        """Get access token from AzamPay"""
        try:
            # Check if we have a valid token
            if self.access_token and self.token_expiry:
                # Make both datetime objects timezone-aware for comparison
                now_utc = datetime.now(timezone.utc)
                # Ensure token_expiry is timezone-aware
                if self.token_expiry.tzinfo is None:
                    token_expiry_aware = self.token_expiry.replace(tzinfo=timezone.utc)
                else:
                    token_expiry_aware = self.token_expiry
                
                if now_utc < token_expiry_aware:
                    logger.info("✅ Using cached AzamPay token")
                    return True
            
            url = f"{self.auth_url}/AppRegistration/GenerateToken"
            
            payload = {
                "appName": self.app_name,
                "clientId": self.client_id,
                "clientSecret": self.client_secret
            }
            
            headers = {
                "Content-Type": "application/json"
            }
            
            logger.info("🔐 Authenticating with AzamPay...")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('success') and data.get('data', {}).get('accessToken'):
                        self.access_token = data['data']['accessToken']
                        
                        # Parse expiry time and make it timezone-aware
                        expire_str = data['data'].get('expire')
                        if expire_str:
                            # Parse ISO format and ensure UTC timezone
                            self.token_expiry = datetime.fromisoformat(
                                expire_str.replace('Z', '+00:00')
                            )
                        else:
                            # Default to 1 hour if no expiry provided
                            self.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
                        
                        logger.info("✅ AzamPay authentication successful!")
                        return True
                    else:
                        logger.error(f"❌ Authentication failed: {data.get('message', 'Unknown error')}")
                        return False
                else:
                    logger.error(f"❌ Authentication failed with status {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Authentication error: {str(e)}")
            return False
    
    async def initiate_payment(
        self,
        phone: str,
        amount: float,
        order_id: str,
        payment_provider: str,
        customer_email: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> Dict:
        """
        Initiate mobile money payment via AzamPay
        
        Args:
            phone: Customer phone number (e.g., '0741361767' or '255741361767')
            amount: Amount in TZS
            order_id: Unique order identifier
            payment_provider: mpesa, tigo, airtel, halopesa, azampesa
            customer_email: Optional (not used by AzamPay)
            customer_name: Optional (not used by AzamPay)
        
        Returns:
            Dict with payment reference and status
        """
        try:
            # Authenticate first
            if not await self.authenticate():
                raise Exception("Authentication failed")
            
            # Map payment provider to AzamPay provider codes
            provider_mapping = {
                'mpesa': 'Mpesa',
                'tigo': 'Tigo',
                'tigopesa': 'Tigo',
                'airtel': 'Airtel',
                'halopesa': 'Halopesa',
                'azampesa': 'Azampesa'
            }
            
            provider_code = provider_mapping.get(payment_provider.lower())
            if not provider_code:
                raise ValueError(f"Unsupported payment provider: {payment_provider}")
            
            # Format phone number (remove leading zero if present, add country code)
            clean_phone = phone.replace('+', '').replace(' ', '')
            if clean_phone.startswith('0'):
                clean_phone = '255' + clean_phone[1:]
            elif not clean_phone.startswith('255'):
                clean_phone = '255' + clean_phone
            
            # Generate external ID with timestamp
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
            external_id = f"ZENTRYA_{order_id}_{timestamp}"
            
            # Prepare request payload
            payload = {
                "accountNumber": clean_phone,
                "amount": str(int(amount)),  # AzamPay expects string
                "currency": "TZS",
                "externalId": external_id,
                "provider": provider_code
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.access_token}"
            }
            
            # Add X-API-Key if available
            if self.x_api_key:
                headers["X-API-Key"] = self.x_api_key
            
            # Try MNO checkout first (direct USSD push)
            url = f"{self.base_url}/azampay/mno/checkout"
            
            logger.info(f"💳 Initiating AzamPay payment for order {order_id}")
            logger.info(f"📱 Phone: {clean_phone}, Amount: {amount} TZS, Provider: {provider_code}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                logger.info(f"📡 AzamPay Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    # Try to parse JSON response
                    try:
                        result = response.json()
                        logger.info(f"✅ AzamPay MNO checkout initiated: {external_id}")
                        
                        return {
                            "reference": external_id,
                            "transaction_id": external_id,
                            "order_id": order_id,
                            "status": "pending",
                            "provider": provider_code,
                            "phone": clean_phone,
                            "amount": amount,
                            "data": result
                        }
                    except json.JSONDecodeError:
                        # Response might be a URL string
                        response_text = response.text.strip()
                        
                        if response_text.startswith('http'):
                            # Web checkout URL returned
                            checkout_url = response_text.strip('"')
                            logger.info(f"✅ AzamPay web checkout URL generated: {external_id}")
                            
                            return {
                                "reference": external_id,
                                "transaction_id": external_id,
                                "order_id": order_id,
                                "status": "pending",
                                "provider": provider_code,
                                "phone": clean_phone,
                                "amount": amount,
                                "checkout_url": checkout_url
                            }
                        else:
                            # Unknown response format, but 200 OK
                            logger.info(f"✅ AzamPay payment initiated: {external_id}")
                            
                            return {
                                "reference": external_id,
                                "transaction_id": external_id,
                                "order_id": order_id,
                                "status": "pending",
                                "provider": provider_code,
                                "phone": clean_phone,
                                "amount": amount
                            }
                else:
                    error_msg = f"Payment initiation failed with status {response.status_code}"
                    logger.error(f"❌ AzamPay error: {error_msg}")
                    logger.error(f"Response: {response.text}")
                    raise Exception(error_msg)
                    
        except Exception as e:
            logger.error(f"❌ AzamPay initiation error: {e}")
            raise
    
    async def check_payment_status(self, reference: str) -> Dict:
        """
        Check payment status from AzamPay
        
        Args:
            reference: Payment reference (external_id) from initiate_payment
        
        Returns:
            Dict with payment status
        """
        try:
            # Authenticate first
            if not await self.authenticate():
                logger.error("❌ Authentication failed during status check")
                return {
                    "status": "pending",
                    "reference": reference,
                    "error": "Authentication failed"
                }
            
            url = f"{self.base_url}/api/v1/Partner/GetTransactionStatus"
            
            params = {
                "referenceId": reference
            }
            
            headers = {
                "Authorization": f"Bearer {self.access_token}"
            }
            
            if self.x_api_key:
                headers["X-API-Key"] = self.x_api_key
            
            logger.info(f"🔍 Checking AzamPay transaction status: {reference}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Map AzamPay status to our status
                    azampay_status = result.get('status', 'PENDING')
                    status_mapping = {
                        'SUCCESS': 'completed',
                        'COMPLETED': 'completed',
                        'PENDING': 'pending',
                        'FAILED': 'failed',
                        'CANCELLED': 'failed',
                        'EXPIRED': 'failed'
                    }
                    
                    mapped_status = status_mapping.get(azampay_status.upper(), 'pending')
                    
                    logger.info(f"✅ Transaction status retrieved: {reference} -> {mapped_status}")
                    
                    return {
                        "status": mapped_status,
                        "reference": reference,
                        "transaction_id": result.get('transactionId', reference),
                        "raw_status": azampay_status,
                        "data": result
                    }
                else:
                    logger.warning(f"⚠️ Status check returned {response.status_code}, assuming pending")
                    return {
                        "status": "pending",
                        "reference": reference
                    }
                    
        except Exception as e:
            logger.error(f"❌ Status check error: {e}")
            # Return pending status on error to allow retry
            return {
                "status": "pending",
                "reference": reference,
                "error": str(e)
            }

# Global instance
azampay_service = AzamPayService()