# app/db/seed.py
"""Seed database with initial users (admin + client) using Argon2."""

from sqlalchemy.orm import Session
from ..database import Base, engine, SessionLocal
from ..models.user import User
from argon2 import PasswordHasher
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ph = PasswordHasher()

# 🧩 Users to seed
users_to_seed = [
    {
        "full_name": "Admin User",
        "email": "admin@zentrya.com",
        "password": "admin123",
        "is_superuser": True,
        "is_active": True,
        "role": "admin",
    },
    {
        "full_name": "Client User",
        "email": "client@zentrya.com",
        "password": "client123",
        "is_superuser": False,
        "is_active": True,
        "role": "client",
    },
]

# -----------------------------------------------------------------------------------

def create_tables():
    """Create database tables if they don't exist."""
    print("\n" + "=" * 80)
    print("STEP 1: CREATING DATABASE TABLES")
    print("=" * 80)
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ All tables created successfully!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

# -----------------------------------------------------------------------------------

def get_password_hash(password: str) -> str:
    """Hash password using Argon2."""
    return ph.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password using Argon2."""
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except Exception:
        return False

# -----------------------------------------------------------------------------------

def seed_users(db: Session):
    """Insert admin and client users into database."""
    print("\n" + "=" * 80)
    print("STEP 2: SEEDING USERS")
    print("=" * 80)

    for user_data in users_to_seed:
        email = user_data["email"]
        existing = db.query(User).filter(User.email == email).first()

        if existing:
            print(f"⏭️  User {email} already exists, skipping...")
            continue

        try:
            hashed_password = get_password_hash(user_data["password"])
            user = User(
                full_name=user_data["full_name"],
                email=email,
                hashed_password=hashed_password,
                is_superuser=user_data["is_superuser"],
                is_active=user_data["is_active"],
                role=user_data["role"],
                email_verified=True,
                phone_verified=False,
            )
            db.add(user)
            db.flush()

            print(f"\n🧍 Created user: {user.full_name}")
            print(f"   Email: {user.email}")
            print(f"   Role: {user.role}")
            print(f"   Superuser: {user.is_superuser}")
            print(f"   Hash (preview): {hashed_password[:60]}...")

            verified = verify_password(user_data["password"], user.hashed_password)
            print(f"   Password verification: {'✅ PASS' if verified else '❌ FAIL'}")

            if not verified:
                raise Exception(f"Password verification failed for {email}!")

        except Exception as e:
            print(f"❌ Error creating {email}: {e}")
            db.rollback()
            raise

    db.commit()
    print("\n✅ All users seeded successfully!")

# -----------------------------------------------------------------------------------

def verify_database(db: Session):
    """Check that all seeded users are valid."""
    print("\n" + "=" * 80)
    print("STEP 3: VERIFYING USERS")
    print("=" * 80)

    users = db.query(User).all()
    if not users:
        print("❌ No users found!")
        return False

    test_creds = {
        "admin@zentrya.com": "admin123",
        "client@zentrya.com": "client123",
    }

    all_passed = True
    for email, password in test_creds.items():
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ {email} not found.")
            all_passed = False
            continue

        ok = verify_password(password, user.hashed_password)
        print(f"{'✅' if ok else '❌'} {email} | Role: {user.role} | Superuser: {user.is_superuser}")
        all_passed &= ok

    return all_passed

# -----------------------------------------------------------------------------------

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print("\n🚀 ZENTRYA DATABASE SEEDER (Argon2)\n")
        create_tables()
        seed_users(db)
        success = verify_database(db)

        print("=" * 80)
        if success:
            print("✅ SEEDING COMPLETE — Ready to log in!")
            print("\nTest Credentials:")
            print("  Admin Panel → admin@zentrya.com / admin123")
            print("  App Client  → client@zentrya.com / client123")
        else:
            print("⚠️ Some verifications failed, check logs above.")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        exit(1)
    finally:
        db.close()
