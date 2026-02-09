# app/db/seed_genres_categories.py
"""Seed genres and categories into the database"""
from sqlalchemy.orm import Session
from ..models import Genre, Category
from ..database import SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Genre seed data
GENRES = [
    {"name": "Action", "slug": "action", "description": "High-energy films with fights, chases, and explosions"},
    {"name": "Drama", "slug": "drama", "description": "Character-driven stories with emotional depth"},
    {"name": "Comedy", "slug": "comedy", "description": "Humorous films designed to make you laugh"},
    {"name": "Horror", "slug": "horror", "description": "Scary and suspenseful films"},
    {"name": "Romance", "slug": "romance", "description": "Love stories and romantic relationships"},
    {"name": "Sci-Fi", "slug": "sci-fi", "description": "Science fiction and futuristic stories"},
    {"name": "Fantasy", "slug": "fantasy", "description": "Magical worlds and fantasy adventures"},
    {"name": "Thriller", "slug": "thriller", "description": "Suspenseful and intense stories"},
    {"name": "Adventure", "slug": "adventure", "description": "Exciting journeys and expeditions"},
    {"name": "Documentary", "slug": "documentary", "description": "Factual and educational content"},
]

# Category seed data
CATEGORIES = [
    {"name": "Movies", "slug": "movies", "description": "Feature-length films"},
    {"name": "Series", "slug": "series", "description": "Television series and shows"},
    {"name": "Originals", "slug": "originals", "description": "Original exclusive content"},
    {"name": "Trending", "slug": "trending", "description": "Currently trending content"},
    {"name": "New Releases", "slug": "new-releases", "description": "Recently released content"},
]


def seed_genres(db: Session):
    """Seed genres into database"""
    logger.info("Seeding genres...")
    
    for genre_data in GENRES:
        # Check if genre already exists
        existing = db.query(Genre).filter(Genre.slug == genre_data["slug"]).first()
        if existing:
            logger.info(f"Genre '{genre_data['name']}' already exists, skipping...")
            continue
        
        genre = Genre(
            name=genre_data["name"],
            slug=genre_data["slug"],
            description=genre_data["description"],
            is_active=True
        )
        db.add(genre)
        logger.info(f"Added genre: {genre_data['name']}")
    
    db.commit()
    logger.info("✅ Genres seeded successfully!")


def seed_categories(db: Session):
    """Seed categories into database"""
    logger.info("Seeding categories...")
    
    for category_data in CATEGORIES:
        # Check if category already exists
        existing = db.query(Category).filter(Category.slug == category_data["slug"]).first()
        if existing:
            logger.info(f"Category '{category_data['name']}' already exists, skipping...")
            continue
        
        category = Category(
            name=category_data["name"],
            slug=category_data["slug"],
            description=category_data["description"],
            is_active=True
        )
        db.add(category)
        logger.info(f"Added category: {category_data['name']}")
    
    db.commit()
    logger.info("✅ Categories seeded successfully!")


def main():
    """Main seed function"""
    db = SessionLocal()
    
    try:
        print("\n" + "="*80)
        print("SEEDING GENRES AND CATEGORIES")
        print("="*80 + "\n")
        
        seed_genres(db)
        seed_categories(db)
        
        # Display what was seeded
        total_genres = db.query(Genre).count()
        total_categories = db.query(Category).count()
        
        print("\n" + "="*80)
        print(f"✅ Total Genres: {total_genres}")
        print(f"✅ Total Categories: {total_categories}")
        print("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Error seeding data: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()