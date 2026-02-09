import logging
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models.user import User
from .utils.security import get_password_hash
from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db(db: Session) -> None:
    """Initialize database with first superuser"""
    
    # Check if superuser already exists
    user = db.query(User).filter(User.email == settings.FIRST_SUPERUSER_EMAIL).first()
    if not user:
        user = User(
            email=settings.FIRST_SUPERUSER_EMAIL,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            full_name="Super Admin",
            is_superuser=True,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Superuser created: {settings.FIRST_SUPERUSER_EMAIL}")
    else:
        logger.info("Superuser already exists")

def main() -> None:
    """Main function to initialize database"""
    logger.info("Creating initial data")
    db = SessionLocal()
    init_db(db)
    logger.info("Initial data created")

if __name__ == "__main__":
    main()