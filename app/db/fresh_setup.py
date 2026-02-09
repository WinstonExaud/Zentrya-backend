# app/db/fresh_setup.py
"""Fresh database setup - creates tables and seeds with argon2"""
from sqlalchemy.orm import Session
from ..database import Base, engine, SessionLocal
from ..models.user import User
from ..utils.security import get_password_hash, verify_password
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users_to_seed = [
    {
        "full_name": "Admin User",
        "email": "admin@zentrya.com",
        "password": "admin123",
        "is_superuser": True,
        "is_active": True,
    },
    {
        "full_name": "Test User",
        "email": "user@zentrya.com",
        "password": "user123",
        "is_superuser": False,
        "is_active": True,
    },
]

def create_tables():
    """Create all database tables"""
    print("\n" + "="*80)
    print("STEP 1: CREATING DATABASE TABLES")
    print("="*80)
    
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ All tables created successfully!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

def seed_users(db: Session):
    """Seed users with argon2 hashed passwords"""
    print("\n" + "="*80)
    print("STEP 2: SEEDING USERS WITH ARGON2")
    print("="*80)
    
    for user_data in users_to_seed:
        try:
            email = user_data["email"]
            
            # Check if user exists
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                print(f"\n⏭️  User {email} already exists, skipping...")
                continue
            
            # Hash password
            hashed_password = get_password_hash(user_data["password"])
            
            # Create user
            user = User(
                full_name=user_data["full_name"],
                email=user_data["email"],
                hashed_password=hashed_password,
                is_superuser=user_data["is_superuser"],
                is_active=user_data["is_active"],
            )
            
            db.add(user)
            db.flush()
            
            print(f"\n📝 User: {user_data['full_name']}")
            print(f"   Email: {email}")
            print(f"   Superuser: {user_data['is_superuser']}")
            print(f"   Hash: {hashed_password[:60]}...")
            
            # Verify immediately
            verified = verify_password(user_data["password"], user.hashed_password)
            print(f"   Verification (pre-commit): {'✅ PASS' if verified else '❌ FAIL'}")
            
            if not verified:
                raise Exception(f"Password verification failed for {email}!")
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
            db.rollback()
            raise
    
    # Commit all
    db.commit()
    print("\n✅ All users seeded successfully!")

def verify_database(db: Session):
    """Verify all users and their passwords"""
    print("\n" + "="*80)
    print("STEP 3: VERIFYING DATABASE")
    print("="*80)
    
    users = db.query(User).all()
    
    if not users:
        print("❌ No users found in database!")
        return False
    
    print(f"\n✅ Found {len(users)} users:\n")
    
    test_creds = {
        'admin@zentrya.com': 'admin123',
        'user@zentrya.com': 'user123',
    }
    
    all_passed = True
    for email, password in test_creds.items():
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            print(f"❌ User {email} NOT FOUND")
            all_passed = False
            continue
        
        try:
            verified = verify_password(password, user.hashed_password)
            status = "✅ PASS" if verified else "❌ FAIL"
            print(f"{status} | {email}")
            print(f"      Password: {password}")
            print(f"      Hash (from DB): {user.hashed_password[:60]}...")
            print(f"      Is Active: {user.is_active}")
            print(f"      Is Superuser: {user.is_superuser}\n")
            
            if not verified:
                all_passed = False
        except Exception as e:
            print(f"❌ {email} - Error: {e}\n")
            all_passed = False
    
    return all_passed

if __name__ == "__main__":
    db = SessionLocal()
    
    try:
        print("\n🚀 FRESH DATABASE SETUP FOR ARGON2\n")
        
        # Step 1: Create tables
        create_tables()
        
        # Step 2: Seed users
        seed_users(db)
        
        # Step 3: Verify
        all_passed = verify_database(db)
        
        print("="*80)
        if all_passed:
            print("✅ SETUP COMPLETE - Ready for login!")
            print("\nTest credentials:")
            print("  admin@zentrya.com : admin123")
            print("  user@zentrya.com : user123")
        else:
            print("❌ SETUP FAILED - See errors above")
            exit(1)
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        exit(1)
    finally:
        db.close()