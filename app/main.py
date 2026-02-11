# app/main.py
import subprocess
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
from typing import Callable

from .config import settings
from .api.v1.router import api_router
from .database import init_db, close_db, get_db_stats, check_db_health
from .redis_client import redis_client, get_redis_stats
from .utils.storage import cleanup_storage_service
from .utils.otp import cleanup_otp_service
from .utils.notifications import cleanup_notification_service

# ============================================================
# Setup Logging
# ============================================================
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# Startup/Shutdown Events
# ============================================================

async def sync_system_time():
    """Sync container time with NTP server"""
    try:
        logger.info("⏱️ Syncing system time with NTP...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["chronyd", "-q", "server", "pool.ntp.org", "iburst"],
                check=False,
                capture_output=True
            )
        )
        logger.info("✅ Time sync complete!")
    except Exception as e:
        logger.warning(f"⚠️ Time sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan with proper async startup/shutdown
    """
    # ✅ STARTUP
    logger.info("🚀 Starting Zentrya API...")
    logger.info(f"🌐 Environment: {getattr(settings, 'ENVIRONMENT', 'development')}")
    logger.info(f"🔒 Debug mode: {settings.DEBUG}")
    
    startup_tasks = []
    
    # 1. Initialize database
    startup_tasks.append(init_db())
    
    # 2. Sync system time
    startup_tasks.append(sync_system_time())
    
    # 3. Connect to Redis
    async def connect_redis():
        try:
            await redis_client.connect()
            logger.info("✅ Redis connected successfully")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            logger.warning("⚠️ API will continue without Redis caching")
    
    startup_tasks.append(connect_redis())
    
    # Run all startup tasks concurrently
    try:
        await asyncio.gather(*startup_tasks)
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    
    # Create uploads directory
    uploads_dir = settings.UPLOAD_DIR
    os.makedirs(uploads_dir, exist_ok=True)
    logger.info(f"📁 Uploads directory ready: {uploads_dir}")
    
    logger.info("✅ Application startup complete!")
    
    yield  # Application runs
    
    # ❌ SHUTDOWN
    logger.info("🛑 Shutting down Zentrya API...")
    
    shutdown_tasks = []
    
    # 1. Close database connections
    shutdown_tasks.append(close_db())
    
    # 2. Disconnect Redis
    async def disconnect_redis():
        try:
            await redis_client.disconnect()
            logger.info("✅ Redis disconnected")
        except Exception as e:
            logger.error(f"⚠️ Redis disconnect error: {e}")
    
    shutdown_tasks.append(disconnect_redis())
    
    # Run shutdown tasks concurrently
    await asyncio.gather(*shutdown_tasks, return_exceptions=True)
    
    # 3. Cleanup thread pools (sync operations)
    cleanup_storage_service()
    cleanup_otp_service()
    cleanup_notification_service()
    
    logger.info("👋 Goodbye!")


# ============================================================
# Create FastAPI Application
# ============================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="High-Performance API for Zentrya Streaming Platform",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
    }
)

# ============================================================
# Middleware Configuration
# ============================================================

# 1️⃣ CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "X-Content-Range", "X-Total-Count"],
    max_age=3600,
)

# 2️⃣ Request ID Middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next: Callable):
    """Add unique request ID for tracing"""
    import uuid
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# 3️⃣ Request Logging Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next: Callable):
    """Log all requests with timing"""
    import time
    
    start_time = time.time()
    
    # Log request
    logger.info(f"➡️ {request.method} {request.url.path}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = time.time() - start_time
    
    # Log response
    logger.info(
        f"⬅️ {request.method} {request.url.path} "
        f"[{response.status_code}] {duration:.3f}s"
    )
    
    response.headers["X-Process-Time"] = str(duration)
    return response

# 4️⃣ Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next: Callable):
    """Add security headers to all responses"""
    response = await call_next(request)
    
    if getattr(settings, 'HTTPS_ONLY', False):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    return response

# ============================================================
# Static Files
# ============================================================

if os.path.exists(settings.UPLOAD_DIR):
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
    logger.info(f"📁 Mounted uploads: {settings.UPLOAD_DIR}")

# ============================================================
# API Routers
# ============================================================

# Main API router
app.include_router(api_router, prefix="/api/v1")

# Auth routers (if separate)
try:
    from .api.v1 import auth
    app.include_router(auth.client_router, prefix="/api/v1", tags=["auth-client"])
    app.include_router(auth.admin_router, prefix="/api/v1", tags=["auth-admin"])
    logger.info("✅ Auth routers loaded")
except ImportError:
    logger.info("ℹ️ Using auth from main api_router")

# ============================================================
# Root Endpoints
# ============================================================

@app.get("/", tags=["Root"])
async def root() -> dict:
    """API information endpoint"""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "message": "Welcome to Zentrya API",
        "docs": "/docs" if settings.DEBUG else None,
        "health": "/health"
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """
    Fast health check endpoint for load balancers
    Returns immediately without checking dependencies
    """
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": asyncio.get_event_loop().time()
    }


@app.get("/health/detailed", tags=["Health"])
async def health_check_detailed() -> dict:
    """
    Detailed health check endpoint
    Checks database and Redis connectivity
    """
    health_status = {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": asyncio.get_event_loop().time()
    }
    
    # Check database
    try:
        db_healthy = await check_db_health()
        health_status["database"] = "connected" if db_healthy else "disconnected"
    except Exception as e:
        health_status["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        redis_healthy = await redis_client.ping()
        health_status["redis"] = "connected" if redis_healthy else "disconnected"
    except Exception as e:
        health_status["redis"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status


@app.get("/metrics", tags=["Monitoring"])
async def metrics() -> dict:
    """
    Metrics endpoint for monitoring
    Returns database, Redis, and storage statistics
    """
    try:
        db_stats = await get_db_stats()
        redis_stats = await get_redis_stats()
        
        from .services.storage import storage_service
        storage_stats = storage_service.get_upload_stats()
        
        return {
            "database": db_stats,
            "redis": redis_stats,
            "storage": storage_stats,
            "environment": getattr(settings, 'ENVIRONMENT', 'unknown'),
            "debug": settings.DEBUG
        }
    except Exception as e:
        logger.error(f"❌ Metrics error: {e}")
        return {
            "error": str(e),
            "environment": getattr(settings, 'ENVIRONMENT', 'unknown')
        }


@app.get("/redis/stats", tags=["Monitoring"])
async def redis_stats() -> dict:
    """Get detailed Redis statistics"""
    try:
        stats = await get_redis_stats()
        return stats
    except Exception as e:
        logger.error(f"❌ Redis stats error: {e}")
        return {"error": str(e)}

# ============================================================
# Exception Handlers
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    request_id = getattr(request.state, "request_id", "unknown")
    
    logger.error(
        f"❌ Unhandled exception [Request ID: {request_id}]: {str(exc)}",
        exc_info=True
    )
    
    # Hide internal errors in production
    error_detail = str(exc) if settings.DEBUG else "Internal server error"
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": error_detail,
            "request_id": request_id
        }
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler"""
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Endpoint not found",
            "path": str(request.url.path)
        }
    )

# ============================================================
# Run Application
# ============================================================

if __name__ == "__main__":
    import uvicorn
    
    # Production-ready uvicorn configuration
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        workers=1 if settings.DEBUG else 4,
        loop="uvloop",
        http="httptools",
        access_log=settings.DEBUG,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )