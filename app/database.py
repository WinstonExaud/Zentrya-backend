from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool
from typing import AsyncGenerator, Generator
import logging
from urllib.parse import urlparse, parse_qs

from .config import settings

logger = logging.getLogger(__name__) 

# ============================================================
# Async Database Engine (PRIMARY - for async endpoints)
# ============================================================

# Parse the DATABASE_URL to extract SSL settings
def parse_database_url(url: str) -> tuple[str, dict]:
    """
    Parse database URL and extract SSL settings for asyncpg.
    Returns: (clean_url, ssl_settings)
    """
    # Remove sslmode and channel_binding from URL
    clean_url = url.split('?')[0]  # Get base URL without query params
    
    # Convert to asyncpg format
    clean_url = clean_url.replace(
        'postgresql+psycopg2://', 
        'postgresql+asyncpg://'
    ).replace(
        'postgresql://',
        'postgresql+asyncpg://'
    )
    
    # Extract SSL settings from original URL
    ssl_settings = {}
    if 'sslmode=require' in url or 'sslmode' in url:
        ssl_settings['ssl'] = 'require'
    
    return clean_url, ssl_settings


# Parse the URL
ASYNC_DATABASE_URL, ssl_config = parse_database_url(settings.DATABASE_URL)

# Create async engine with optimized pooling
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=1800,
    connect_args={
        "server_settings": {
            "application_name": "zentrya_api",
            "jit": "off",
        },
        "command_timeout": 60,
        "timeout": 10,
        **ssl_config,  # ✅ Add SSL config here (extracted from URL)
    },
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False,
)

# ============================================================
# Sync Database Engine (FALLBACK - for backwards compatibility)
# ============================================================

# Sync engine with connection pooling
sync_engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    pool_pre_ping=True,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
    connect_args={
        "options": "-c timezone=Africa/Dar_es_Salaam"
    }
)

# Sync session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
    expire_on_commit=False
)

# ============================================================
# Base Model
# ============================================================

Base = declarative_base()

# ============================================================
# Database Session Dependencies
# ============================================================

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async database session dependency for FastAPI endpoints.
    Use this for all new async endpoints.
    
    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(Item))
            return result.scalars().all()
    
    IMPORTANT: 
    - FastAPI handles commit/rollback automatically based on response status
    - Don't manually commit/rollback in endpoints unless you have a specific reason
    - Session is automatically closed after the request
    """
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


def get_db() -> Generator[Session, None, None]:
    """
    Sync database session dependency (legacy support).
    Use get_async_db() for new endpoints.
    
    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# Database Health Check
# ============================================================

async def check_db_health() -> bool:
    """
    Check if database is accessible and responsive.
    Returns True if healthy, False otherwise.
    """
    session = AsyncSessionLocal()
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
    finally:
        await session.close()


async def get_db_stats() -> dict:
    """
    Get database connection pool statistics.
    """
    return {
        "async_pool": {
            "size": async_engine.pool.size(),
            "checked_in": async_engine.pool.checkedin(),
            "checked_out": async_engine.pool.checkedout(),
            "overflow": async_engine.pool.overflow(),
            "total": async_engine.pool.size() + async_engine.pool.overflow(),
        },
        "sync_pool": {
            "size": sync_engine.pool.size(),
            "checked_in": sync_engine.pool.checkedin(),
            "checked_out": sync_engine.pool.checkedout(),
            "overflow": sync_engine.pool.overflow(),
            "total": sync_engine.pool.size() + sync_engine.pool.overflow(),
        }
    }


# ============================================================
# Connection Event Listeners (for logging & monitoring)
# ============================================================

@event.listens_for(sync_engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Log database connections"""
    logger.debug("Database connection established (sync)")


@event.listens_for(sync_engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when connection is checked out from pool"""
    logger.debug("Connection checked out from pool (sync)")


# ============================================================
# Startup/Shutdown Handlers
# ============================================================

async def init_db():
    try:
        logger.info("🔄 Checking database connection...")

        # just verify connectivity
        is_healthy = await check_db_health()
        if is_healthy:
            logger.info("✅ Database health check passed")
        else:
            logger.error("❌ Database health check failed")

    except Exception as e:
        logger.error(f"❌ Database init failed: {e}", exc_info=True)
        raise


async def close_db():
    """
    Close database connections on shutdown.
    """
    try:
        logger.info("🔄 Closing database connections...")
        
        await async_engine.dispose()
        sync_engine.dispose()
        
        logger.info("✅ Database connections closed")
    except Exception as e:
        logger.error(f"❌ Error closing database: {e}")


# ============================================================
# Utility Functions
# ============================================================

async def execute_raw_sql(query: str, params: dict = None) -> list:
    """
    Execute raw SQL query asynchronously.
    
    Usage:
        results = await execute_raw_sql(
            "SELECT * FROM users WHERE email = :email",
            {"email": "user@example.com"}
        )
    """
    session = AsyncSessionLocal()
    try:
        result = await session.execute(text(query), params or {})
        return result.fetchall()
    finally:
        await session.close()


# ============================================================
# Export primary dependency
# ============================================================

# Primary async dependency (use this for new code)
get_db_session = get_async_db

__all__ = [
    'Base',
    'async_engine',
    'sync_engine',
    'AsyncSessionLocal',
    'SessionLocal',
    'get_async_db',
    'get_db',
    'get_db_session',
    'check_db_health',
    'get_db_stats',
    'init_db',
    'close_db',
] 