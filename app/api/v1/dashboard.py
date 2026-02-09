# app/api/v1/dashboard.py
"""Complete dashboard endpoints for stats, analytics, and admin overview"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional
import logging

from ...database import get_db
from ...models.user import User, UserRole
from ...models.movie import Movie

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ==================== DASHBOARD STATS ====================

@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Get comprehensive dashboard statistics including:
    - Total movies, series, users, views
    - Percentage changes compared to last month
    - Trend indicators (up/down)
    """
    try:
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        sixty_days_ago = datetime.utcnow() - timedelta(days=60)
        
        # ========== MOVIES ==========
        total_movies = db.query(func.count(Movie.id)).scalar() or 0
        movies_last_month = db.query(func.count(Movie.id)).filter(
            Movie.created_at >= thirty_days_ago
        ).scalar() or 0
        movies_previous_month = db.query(func.count(Movie.id)).filter(
            Movie.created_at >= sixty_days_ago,
            Movie.created_at < thirty_days_ago
        ).scalar() or 0
        movies_change = calculate_percentage_change(movies_last_month, movies_previous_month)
        movies_trend = "up" if movies_last_month >= movies_previous_month else "down"
        
        # ========== SERIES ==========
        # TODO: Update when Series model is ready
        total_series = 0
        series_change = "+0%"
        series_trend = "up"
        
        # Try to get series stats if Series model exists
        try:
            from ...models.series import Series
            total_series = db.query(func.count(Series.id)).scalar() or 0
            series_last_month = db.query(func.count(Series.id)).filter(
                Series.created_at >= thirty_days_ago
            ).scalar() or 0
            series_previous_month = db.query(func.count(Series.id)).filter(
                Series.created_at >= sixty_days_ago,
                Series.created_at < thirty_days_ago
            ).scalar() or 0
            series_change = calculate_percentage_change(series_last_month, series_previous_month)
            series_trend = "up" if series_last_month >= series_previous_month else "down"
        except ImportError:
            logger.info("Series model not available yet")
        
        # ========== USERS ==========
        total_users = db.query(func.count(User.id)).scalar() or 0
        users_last_month = db.query(func.count(User.id)).filter(
            User.created_at >= thirty_days_ago
        ).scalar() or 0
        users_previous_month = db.query(func.count(User.id)).filter(
            User.created_at >= sixty_days_ago,
            User.created_at < thirty_days_ago
        ).scalar() or 0
        users_change = calculate_percentage_change(users_last_month, users_previous_month)
        users_trend = "up" if users_last_month >= users_previous_month else "down"
        
        # Active users (logged in within last 30 days)
        active_users = users_last_month
        if hasattr(User, 'last_login'):
            active_users = db.query(func.count(User.id)).filter(
                User.last_login >= thirty_days_ago
            ).scalar() or 0
        
        # ========== VIEWS ==========
        total_views = db.query(func.sum(Movie.view_count)).scalar() or 0
        
        # Calculate views for movies created in last month
        views_last_month = db.query(func.sum(Movie.view_count)).filter(
            Movie.created_at >= thirty_days_ago
        ).scalar() or 0
        
        # Calculate views for movies from previous month
        views_previous_month = db.query(func.sum(Movie.view_count)).filter(
            Movie.created_at >= sixty_days_ago,
            Movie.created_at < thirty_days_ago
        ).scalar() or 0
        
        views_change = calculate_percentage_change(views_last_month, views_previous_month)
        views_trend = "up" if views_last_month >= views_previous_month else "down"
        
        # ========== RETURN DATA ==========
        stats_data = {
            "total_movies": total_movies,
            "total_series": total_series,
            "active_users": active_users,
            "total_users": total_users,
            "total_views": int(total_views),
            "movies_change": movies_change,
            "series_change": series_change,
            "users_change": users_change,
            "views_change": views_change,
            "movies_trend": movies_trend,
            "series_trend": series_trend,
            "users_trend": users_trend,
            "views_trend": views_trend,
        }
        
        logger.info(f"📊 Dashboard stats fetched - Movies: {total_movies}, Users: {total_users}, Views: {total_views}")
        
        return {"data": stats_data}
        
    except Exception as e:
        logger.error(f"❌ Error fetching dashboard stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch dashboard statistics"
        )


# ==================== RECENT MOVIES ====================

@router.get("/recent-movies")
def get_recent_movies(
    limit: int = 5,
    db: Session = Depends(get_db)
):
    """
    Get recently uploaded/updated movies
    """
    try:
        recent_movies = (
            db.query(Movie)
            .order_by(Movie.created_at.desc())
            .limit(limit)
            .all()
        )
        
        movies_data = []
        for movie in recent_movies:
            movies_data.append({
                "id": movie.id,
                "title": movie.title,
                "poster_url": movie.poster_url,
                "thumbnail": movie.poster_url,
                "status": "Published" if movie.is_active else "Draft",
                "is_active": movie.is_active,
                "views": movie.view_count or 0,
                "view_count": movie.view_count or 0,
                "date": movie.created_at.isoformat() if movie.created_at else None,
                "created_at": movie.created_at.isoformat() if movie.created_at else None
            })
        
        logger.info(f"📺 Recent movies fetched: {len(movies_data)} movies")
        
        return {"movies": movies_data}
        
    except Exception as e:
        logger.error(f"❌ Error fetching recent movies: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch recent movies"
        )


# ==================== RECENT ACTIVITY ====================

@router.get("/recent-activity")
def get_recent_activity(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Get recent system activity (movies added, users registered, etc.)
    """
    try:
        activity = []
        
        # Get recent movies added (last 5)
        recent_movies = (
            db.query(Movie)
            .order_by(Movie.created_at.desc())
            .limit(5)
            .all()
        )
        
        for movie in recent_movies:
            activity.append({
                "id": f"movie_{movie.id}",
                "action": f'Movie "{movie.title}" was uploaded',
                "user": "Admin",
                "time": format_time_ago(movie.created_at) if movie.created_at else "Unknown",
                "created_at": movie.created_at.isoformat() if movie.created_at else None,
                "type": "movie_upload"
            })
        
        # Get recent users registered (last 5)
        recent_users = (
            db.query(User)
            .order_by(User.created_at.desc())
            .limit(5)
            .all()
        )
        
        for user in recent_users:
            role = "admin" if user.is_superuser else "client"
            activity.append({
                "id": f"user_{user.id}",
                "action": f'New {role} registered: {user.full_name}',
                "user": user.full_name or "New User",
                "time": format_time_ago(user.created_at) if user.created_at else "Unknown",
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "type": "user_registration"
            })
        
        # Sort by created_at timestamp (most recent first)
        activity.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        # Limit results
        activity = activity[:limit]
        
        logger.info(f"📋 Recent activity fetched: {len(activity)} items")
        
        return {"data": activity}
        
    except Exception as e:
        logger.error(f"❌ Error fetching recent activity: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch recent activity"
        )


# ==================== CONTENT OVERVIEW ====================

@router.get("/content-overview")
def get_content_overview(db: Session = Depends(get_db)):
    """
    Get overview of all content (movies, series, episodes)
    """
    try:
        # Movies stats
        total_movies = db.query(func.count(Movie.id)).scalar() or 0
        active_movies = db.query(func.count(Movie.id)).filter(Movie.is_active == True).scalar() or 0
        featured_movies = db.query(func.count(Movie.id)).filter(Movie.is_featured == True).scalar() or 0
        
        # Series stats (if available)
        total_series = 0
        total_episodes = 0
        
        try:
            from ...models.series import Series, Episode
            total_series = db.query(func.count(Series.id)).scalar() or 0
            total_episodes = db.query(func.count(Episode.id)).scalar() or 0
        except ImportError:
            pass
        
        return {
            "data": {
                "movies": {
                    "total": total_movies,
                    "active": active_movies,
                    "featured": featured_movies
                },
                "series": {
                    "total": total_series,
                    "episodes": total_episodes
                }
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching content overview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch content overview"
        )


# ==================== USER OVERVIEW ====================

@router.get("/user-overview")
def get_user_overview(db: Session = Depends(get_db)):
    """
    Get overview of users (total, active, by role, etc.)
    """
    try:
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Total users
        total_users = db.query(func.count(User.id)).scalar() or 0
        
        # Active users
        active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
        
        # New users this month
        new_users = db.query(func.count(User.id)).filter(
            User.created_at >= thirty_days_ago
        ).scalar() or 0
        
        # Users by role
        admin_count = 0
        client_count = 0
        
        if hasattr(User, 'role'):
            admin_count = db.query(func.count(User.id)).filter(
                User.role == UserRole.ADMIN
            ).scalar() or 0
            client_count = db.query(func.count(User.id)).filter(
                User.role == UserRole.CLIENT
            ).scalar() or 0
        else:
            admin_count = db.query(func.count(User.id)).filter(
                User.is_superuser == True
            ).scalar() or 0
            client_count = total_users - admin_count
        
        return {
            "data": {
                "total": total_users,
                "active": active_users,
                "new_this_month": new_users,
                "admins": admin_count,
                "clients": client_count
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching user overview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user overview"
        )


# ==================== ANALYTICS SUMMARY ====================

@router.get("/analytics-summary")
def get_analytics_summary(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Get analytics summary for specified number of days
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Total views
        total_views = db.query(func.sum(Movie.view_count)).scalar() or 0
        
        # New content
        new_movies = db.query(func.count(Movie.id)).filter(
            Movie.created_at >= start_date
        ).scalar() or 0
        
        # New users
        new_users = db.query(func.count(User.id)).filter(
            User.created_at >= start_date
        ).scalar() or 0
        
        # Most viewed movies
        top_movies = (
            db.query(Movie)
            .order_by(Movie.view_count.desc())
            .limit(5)
            .all()
        )
        
        top_movies_data = [
            {
                "id": movie.id,
                "title": movie.title,
                "views": movie.view_count or 0
            }
            for movie in top_movies
        ]
        
        return {
            "data": {
                "period_days": days,
                "total_views": int(total_views),
                "new_movies": new_movies,
                "new_users": new_users,
                "top_movies": top_movies_data
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching analytics summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch analytics summary"
        )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_percentage_change(current: int, previous: int) -> str:
    """Calculate percentage change between two values"""
    if previous == 0:
        if current > 0:
            return "+100%"
        return "+0%"
    
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def format_large_number(num: int) -> str:
    """Format large numbers as K, M, B"""
    num = int(num) if num else 0
    
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B".rstrip('0').rstrip('.')
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M".rstrip('0').rstrip('.')
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K".rstrip('0').rstrip('.')
    return str(num)


def format_time_ago(dt: datetime) -> str:
    """Format datetime as 'time ago' string"""
    if not dt:
        return "Unknown"
    
    now = datetime.utcnow()
    diff = now - (dt.replace(tzinfo=None) if dt.tzinfo else dt)
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} min ago" if minutes > 1 else "1 min ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    elif seconds < 2592000:  # 30 days
        days = int(seconds / 86400)
        return f"{days} day ago" if days == 1 else f"{days} days ago"
    else:
        return dt.strftime("%b %d, %Y")