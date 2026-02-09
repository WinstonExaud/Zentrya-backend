import asyncio
import logging
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)

async def test_table_creation():
    from app.database import async_engine, Base, AsyncSessionLocal
    
    # Import all models explicitly
    from app.models.user import User
    from app.models.category import Category
    from app.models.genre import Genre
    from app.models.movie import Movie, movie_genres
    from app.models.series import Series, series_genres, Episode
    from app.models.watch_analytics import (
        WatchSession, MovieAnalytics, SeriesAnalytics, EpisodeAnalytics
    )
    from app.models.watch_progress import WatchProgress
    
    print("\n" + "="*60)
    print("🔍 REGISTERED TABLES IN METADATA:")
    print("="*60)
    for table_name in Base.metadata.tables.keys():
        print(f"  ✓ {table_name}")
    print(f"\n📊 Total: {len(Base.metadata.tables)} tables\n")
    
    if not Base.metadata.tables:
        print("❌ ERROR: No tables registered!")
        print("Check that your models inherit from Base correctly.")
        return
    
    print("="*60)
    print("🔨 CREATING TABLES...")
    print("="*60)
    
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    print("✅ create_all() executed\n")
    
    print("="*60)
    print("🔍 CHECKING DATABASE FOR TABLES:")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        db_tables = [row[0] for row in result.fetchall()]
        
        if db_tables:
            for table in db_tables:
                print(f"  ✓ {table}")
            print(f"\n📊 Total in DB: {len(db_tables)} tables")
        else:
            print("  ❌ NO TABLES FOUND IN DATABASE!")
    
    print("="*60 + "\n")
    
    await async_engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_table_creation())