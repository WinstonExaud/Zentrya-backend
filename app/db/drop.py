# app/db/create_tables.py
"""Create all tables fresh"""
from ..database import Base, engine
from ..models import User, Category, Genre, Movie
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_tables():
    """Drop and recreate all tables"""
    logger.info("Creating all tables...")
    
    try:
        # Drop all existing tables
        Base.metadata.drop_all(bind=engine)
        logger.info("Dropped all existing tables")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("Created all tables successfully")
        
        print("\n" + "="*80)
        print("✅ All tables created successfully!")
        print("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_tables()