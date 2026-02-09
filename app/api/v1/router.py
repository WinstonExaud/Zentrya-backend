from fastapi import APIRouter
from . import users, dashboard, movies_hls, genres, categories, upload, series, episodes, payments, subscriptions, watch_progress, my_list, downloads, sessions, avatars, waitlist, notifications, analytics
from .auth import router as auth_router

api_router = APIRouter()

# Include the auth router (now supports both client and admin)
api_router.include_router(auth_router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["user"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(avatars.router, prefix="/avatars", tags=["avatars"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])



# Include other routers
api_router.include_router(users.router, tags=["users"])

api_router.include_router(downloads.router, prefix="/downloads", tags=["downloads"])
api_router.include_router(watch_progress.router, prefix="/watch-progress", tags=["watch-progress"])
api_router.include_router(my_list.router, prefix="/my-list", tags=["my-list"])
api_router.include_router(waitlist.router, prefix="/waitlist", tags=["waitlist"])
api_router.include_router(payments.router, tags=["payments"])
api_router.include_router(subscriptions.router, tags=["subscriptions"])
api_router.include_router(sessions.router, tags=["sessions"])
api_router.include_router(avatars.router, tags=["avatars"])
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(movies_hls.router, tags=["movies"])
api_router.include_router(series.router, tags=["series"])
api_router.include_router(episodes.router, tags=["episodes"])
api_router.include_router(genres.router, tags=["genres"])
api_router.include_router(categories.router, tags=["categories"])
api_router.include_router(upload.router, tags=["upload"])

__all__ = ["api_router"]