"""
Simple configuration test for Docker environment
Place this in: app/tests/test_config.py
"""

import sys
import os

def test_config():
    """Test basic configuration"""
    print("\n" + "="*60)
    print("🔧 ZENTRYA CONFIGURATION TEST")
    print("="*60)
    
    try:
        from app.config import settings
        
        print("\n✅ Config module loaded successfully")
        print(f"\nApp Name: {settings.APP_NAME}")
        print(f"Debug Mode: {settings.DEBUG}")
        print(f"Storage Type: {settings.STORAGE_TYPE}")
        
        # Check R2
        print("\n📦 Cloudflare R2 Configuration:")
        print(f"   Account ID: {'Set' if settings.R2_ACCOUNT_ID else 'Not Set'}")
        print(f"   Access Key: {'Set' if settings.R2_ACCESS_KEY_ID else 'Not Set'}")
        print(f"   Bucket: {settings.R2_BUCKET_NAME or 'Not Set'}")
        print(f"   Public URL: {settings.R2_PUBLIC_URL or 'Not Set'}")
        print(f"   R2 Enabled: {settings.is_r2_enabled}")
        
        # Check Firebase
        print("\n🔥 Firebase Configuration:")
        print(f"   Storage Bucket: {settings.FIREBASE_STORAGE_BUCKET or 'Not Set'}")
        print(f"   Credentials Path: {settings.FIREBASE_CREDENTIALS_PATH or 'Not Set'}")
        creds_exist = os.path.exists(settings.FIREBASE_CREDENTIALS_PATH or '')
        print(f"   Credentials File Exists: {creds_exist}")
        print(f"   Firebase Enabled: {settings.is_firebase_enabled}")
        
        # Check Database
        print("\n🗄️ Database Configuration:")
        print(f"   Database URL: {settings.DATABASE_URL[:30]}...")
        
        # Summary
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        
        if settings.is_r2_enabled:
            print("✅ Cloudflare R2: Ready")
        else:
            print("❌ Cloudflare R2: Not Configured")
            print("   → Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        
        if settings.is_firebase_enabled:
            print("✅ Firebase Storage: Ready")
        else:
            print("❌ Firebase Storage: Not Configured")
            print("   → Set FIREBASE_STORAGE_BUCKET and place firebase-credentials.json")
        
        if settings.is_r2_enabled and settings.is_firebase_enabled:
            print("\n🎉 Both storage services configured! Ready for production.")
        else:
            print("\n⚠️  Please configure the missing storage services.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error loading configuration: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_storage_import():
    """Test if storage module can be imported"""
    print("\n" + "="*60)
    print("📦 STORAGE MODULE TEST")
    print("="*60)
    
    try:
        from app.utils.storage import storage_service
        
        print("\n✅ Storage module imported successfully")
        print(f"   R2 Client: {'Initialized' if storage_service.r2_client else 'Not Initialized'}")
        print(f"   Firebase Bucket: {'Initialized' if storage_service.firebase_bucket else 'Not Initialized'}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error importing storage module: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n🚀 Starting configuration tests...\n")
    
    results = {
        "Config Test": test_config(),
        "Storage Import Test": test_storage_import()
    }
    
    print("\n" + "="*60)
    print("🎯 FINAL RESULTS")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    if all(results.values()):
        print("\n✨ All tests passed!")
        exit(0)
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")
        exit(1)