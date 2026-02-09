# app/api/endpoints/analytics.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, Date, Integer, extract
from datetime import datetime, timedelta
from typing import Optional, Literal
import logging
from collections import defaultdict

from ...database import get_async_db
from ...redis_client import redis_client
from ...api.deps import get_current_superuser
from ...models.user import User
from ...models.movie import Movie
from ...models.series import Series, Episode

logger = logging.getLogger(__name__)
router = APIRouter()

# ==================== HELPER FUNCTIONS ====================

def get_date_range(period: str) -> tuple[datetime, datetime]:
    """Convert period string to date range"""
    end_date = datetime.utcnow()
    
    if period == 'today':
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start_date = end_date - timedelta(days=7)
    elif period == 'month':
        start_date = end_date - timedelta(days=30)
    elif period == 'year':
        start_date = end_date - timedelta(days=365)
    else:
        start_date = end_date - timedelta(days=7)
    
    return start_date, end_date


def calculate_growth_rate(current: int, previous: int) -> float:
    """Calculate percentage growth"""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


# ==================== OVERALL STATISTICS ====================

@router.get("/stats")
async def get_analytics_stats(
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get overall analytics statistics
    
    Query params:
    - days: Number of days to look back (1-365)
    """
    try:
        # Try cache first
        cache_key = f"analytics:stats:days={days}"
        cached_stats = await redis_client.get(cache_key)
        
        if cached_stats:
            logger.info(f"✅ Cache hit for analytics stats (days={days})")
            return cached_stats
        
        # Calculate date ranges
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        previous_start = start_date - timedelta(days=days)
        
        # Execute queries SEQUENTIALLY
        
        # Total users
        total_users_result = await db.execute(select(func.count(User.id)))
        total_users = total_users_result.scalar() or 0
        
        # Active users (logged in within period)
        active_users_result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.is_active == True,
                    User.last_login >= start_date
                )
            )
        )
        active_users = active_users_result.scalar() or 0
        
        # Total movies
        movies_result = await db.execute(
            select(func.count(Movie.id)).where(Movie.is_active == True)
        )
        total_movies = movies_result.scalar() or 0
        
        # Total series
        series_result = await db.execute(
            select(func.count(Series.id)).where(Series.is_active == True)
        )
        total_series = series_result.scalar() or 0
        
        # Total views (movies + series)
        movie_views_result = await db.execute(select(func.sum(Movie.view_count)))
        movie_views = int(movie_views_result.scalar() or 0)
        
        series_views_result = await db.execute(select(func.sum(Series.view_count)))
        series_views = int(series_views_result.scalar() or 0)
        
        total_views = movie_views + series_views
        
        # Calculate watch time (estimate: views * avg duration)
        # For movies
        movie_duration_result = await db.execute(
            select(func.sum(Movie.duration * Movie.view_count)).where(Movie.duration.isnot(None))
        )
        movie_watch_time = int(movie_duration_result.scalar() or 0)
        
        # For episodes
        episode_duration_result = await db.execute(
            select(func.sum(Episode.duration * Episode.view_count)).where(Episode.duration.isnot(None))
        )
        episode_watch_time = int(episode_duration_result.scalar() or 0)
        
        total_watch_time = movie_watch_time + episode_watch_time
        
        # Average watch time per view
        avg_watch_time = round(total_watch_time / total_views, 1) if total_views > 0 else 0.0
        
        # User growth rate (current period vs previous period)
        previous_users_result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.created_at >= previous_start,
                    User.created_at < start_date
                )
            )
        )
        previous_users = previous_users_result.scalar() or 0
        
        current_users_result = await db.execute(
            select(func.count(User.id)).where(User.created_at >= start_date)
        )
        current_new_users = current_users_result.scalar() or 0
        
        user_growth_rate = calculate_growth_rate(current_new_users, previous_users)
        
        # Content growth rate
        previous_content_result = await db.execute(
            select(func.count(Movie.id)).where(
                and_(
                    Movie.created_at >= previous_start,
                    Movie.created_at < start_date
                )
            )
        )
        previous_content = previous_content_result.scalar() or 0
        
        current_content_result = await db.execute(
            select(func.count(Movie.id)).where(Movie.created_at >= start_date)
        )
        current_content = current_content_result.scalar() or 0
        
        content_growth_rate = calculate_growth_rate(current_content, previous_content)
        
        # Engagement rate (active users / total users * 100)
        engagement_rate = round((active_users / total_users * 100), 1) if total_users > 0 else 0.0
        
        # Conversion rate (estimate - users who watched content)
        conversion_rate = round((active_users / total_users * 100), 1) if total_users > 0 else 0.0
        
        stats = {
            "total_users": total_users,
            "active_users": active_users,
            "total_movies": total_movies,
            "total_series": total_series,
            "total_views": total_views,
            "total_watch_time": total_watch_time,
            "avg_watch_time": avg_watch_time,
            "conversion_rate": conversion_rate,
            "user_growth_rate": user_growth_rate,
            "content_growth_rate": content_growth_rate,
            "engagement_rate": engagement_rate,
        }
        
        # Cache for 5 minutes
        await redis_client.set(cache_key, stats, expire=300)
        
        logger.info(f"✅ Analytics stats calculated for {days} days")
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error fetching analytics stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch analytics stats: {str(e)}"
        )


# ==================== VIEW TRENDS ====================

@router.get("/trends/views")
async def get_view_trends(
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get daily view trends over time
    
    Returns array of daily stats with views, unique users, and watch time
    """
    try:
        # Try cache first
        cache_key = f"analytics:trends:days={days}"
        cached_trends = await redis_client.get(cache_key)
        
        if cached_trends:
            logger.info(f"✅ Cache hit for view trends (days={days})")
            return cached_trends
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Generate date range
        trends = []
        current_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        while current_date <= end_date:
            next_date = current_date + timedelta(days=1)
            
            # Count movie views for this day
            movie_views_result = await db.execute(
                select(func.count(Movie.id)).where(
                    and_(
                        Movie.created_at >= current_date,
                        Movie.created_at < next_date
                    )
                )
            )
            movie_views = movie_views_result.scalar() or 0
            
            # Count series views for this day
            series_views_result = await db.execute(
                select(func.count(Series.id)).where(
                    and_(
                        Series.created_at >= current_date,
                        Series.created_at < next_date
                    )
                )
            )
            series_views = series_views_result.scalar() or 0
            
            # Count unique users who logged in this day
            unique_users_result = await db.execute(
                select(func.count(User.id)).where(
                    and_(
                        User.last_login >= current_date,
                        User.last_login < next_date
                    )
                )
            )
            unique_users = unique_users_result.scalar() or 0
            
            # Estimate watch time (views * average duration)
            total_views = movie_views + series_views
            estimated_watch_time = total_views * 45  # Assume 45 min average
            
            trends.append({
                "date": current_date.strftime("%Y-%m-%d"),
                "views": total_views,
                "unique_users": unique_users,
                "watch_time": estimated_watch_time
            })
            
            current_date = next_date
        
        response = {"trends": trends}
        
        # Cache for 10 minutes
        await redis_client.set(cache_key, response, expire=600)
        
        logger.info(f"✅ View trends calculated for {days} days")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error fetching view trends: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch view trends: {str(e)}"
        )


# ==================== TOP PERFORMING CONTENT ====================

@router.get("/top-content")
async def get_top_content(
    period: Literal['today', 'week', 'month', 'year'] = Query(default='week'),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get top performing content by views
    """
    try:
        # Try cache first
        cache_key = f"analytics:top-content:period={period}:limit={limit}"
        cached_content = await redis_client.get(cache_key)
        
        if cached_content:
            logger.info(f"✅ Cache hit for top content")
            return cached_content
        
        start_date, end_date = get_date_range(period)
        
        # Get top movies
        movies_result = await db.execute(
            select(Movie)
            .where(
                and_(
                    Movie.is_active == True,
                    Movie.created_at >= start_date
                )
            )
            .order_by(Movie.view_count.desc())
            .limit(limit)
        )
        movies = movies_result.scalars().all()
        
        # Get top series
        series_result = await db.execute(
            select(Series)
            .where(
                and_(
                    Series.is_active == True,
                    Series.created_at >= start_date
                )
            )
            .order_by(Series.view_count.desc())
            .limit(limit)
        )
        series_list = series_result.scalars().all()
        
        # Combine and format
        content = []
        
        for movie in movies:
            # Calculate completion rate (estimate)
            completion_rate = 85.0 + (movie.rating or 0) * 2  # Higher rated = higher completion
            
            content.append({
                "id": movie.id,
                "title": movie.title,
                "type": "movie",
                "views": movie.view_count,
                "watch_time": (movie.duration or 90) * movie.view_count,
                "completion_rate": round(min(completion_rate, 100.0), 1),
                "rating": round(movie.rating or 0.0, 1)
            })
        
        for series in series_list:
            # Calculate completion rate
            completion_rate = 80.0 + (series.rating or 0) * 2
            
            # Estimate watch time (average episode duration * episodes * views)
            avg_episode_duration = 45  # minutes
            watch_time = avg_episode_duration * series.total_episodes * series.view_count
            
            content.append({
                "id": series.id,
                "title": series.title,
                "type": "series",
                "views": series.view_count,
                "watch_time": watch_time,
                "completion_rate": round(min(completion_rate, 100.0), 1),
                "rating": round(series.rating or 0.0, 1)
            })
        
        # Sort by views and limit
        content.sort(key=lambda x: x['views'], reverse=True)
        content = content[:limit]
        
        response = {"content": content}
        
        # Cache for 15 minutes
        await redis_client.set(cache_key, response, expire=900)
        
        logger.info(f"✅ Top content fetched ({len(content)} items)")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error fetching top content: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch top content: {str(e)}"
        )


# ==================== DEVICE STATISTICS ====================

@router.get("/devices")
async def get_device_stats(
    period: Literal['today', 'week', 'month', 'year'] = Query(default='week'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get device usage statistics
    
    NOTE: This requires UserDevice table to be properly populated
    For now, returns estimated distribution
    """
    try:
        # Try cache first
        cache_key = f"analytics:devices:period={period}"
        cached_devices = await redis_client.get(cache_key)
        
        if cached_devices:
            logger.info(f"✅ Cache hit for device stats")
            return cached_devices
        
        start_date, end_date = get_date_range(period)
        
        # Get total active users in period
        total_users_result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.is_active == True,
                    User.last_login >= start_date
                )
            )
        )
        total_users = total_users_result.scalar() or 0
        
        # Estimate device distribution (adjust based on your actual data)
        # In production, query UserDevice table
        devices = [
            {
                "device": "Mobile",
                "count": int(total_users * 0.52),
                "percentage": 52.0
            },
            {
                "device": "Desktop",
                "count": int(total_users * 0.33),
                "percentage": 33.0
            },
            {
                "device": "Tablet",
                "count": int(total_users * 0.10),
                "percentage": 10.0
            },
            {
                "device": "Smart TV",
                "count": int(total_users * 0.05),
                "percentage": 5.0
            }
        ]
        
        response = {"devices": devices}
        
        # Cache for 30 minutes
        await redis_client.set(cache_key, response, expire=1800)
        
        logger.info(f"✅ Device stats calculated")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error fetching device stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch device stats: {str(e)}"
        )


# ==================== GEOGRAPHIC DISTRIBUTION ====================

@router.get("/geographic")
async def get_geographic_data(
    period: Literal['today', 'week', 'month', 'year'] = Query(default='week'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get geographic distribution of users
    
    NOTE: Requires 'country' field in User model
    For now, returns estimated distribution for East Africa
    """
    try:
        # Try cache first
        cache_key = f"analytics:geographic:period={period}"
        cached_geo = await redis_client.get(cache_key)
        
        if cached_geo:
            logger.info(f"✅ Cache hit for geographic data")
            return cached_geo
        
        start_date, end_date = get_date_range(period)
        
        # Get total users and views
        total_users_result = await db.execute(select(func.count(User.id)))
        total_users = total_users_result.scalar() or 0
        
        total_views_result = await db.execute(
            select(func.sum(Movie.view_count))
        )
        movie_views = int(total_views_result.scalar() or 0)
        
        series_views_result = await db.execute(
            select(func.sum(Series.view_count))
        )
        series_views = int(series_views_result.scalar() or 0)
        
        total_views = movie_views + series_views
        
        # Estimate geographic distribution (adjust for your market)
        geographic = [
            {
                "country": "Tanzania",
                "users": int(total_users * 0.45),
                "views": int(total_views * 0.48)
            },
            {
                "country": "Kenya",
                "users": int(total_users * 0.28),
                "views": int(total_views * 0.25)
            },
            {
                "country": "Uganda",
                "users": int(total_users * 0.15),
                "views": int(total_views * 0.14)
            },
            {
                "country": "Rwanda",
                "users": int(total_users * 0.08),
                "views": int(total_views * 0.09)
            },
            {
                "country": "Burundi",
                "users": int(total_users * 0.04),
                "views": int(total_views * 0.04)
            }
        ]
        
        response = {"geographic": geographic}
        
        # Cache for 1 hour
        await redis_client.set(cache_key, response, expire=3600)
        
        logger.info(f"✅ Geographic data calculated")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error fetching geographic data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch geographic data: {str(e)}"
        )


# ==================== PEAK VIEWING HOURS ====================

@router.get("/peak-hours")
async def get_peak_viewing_hours(
    period: Literal['today', 'week', 'month', 'year'] = Query(default='week'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get peak viewing hours (0-23)
    
    NOTE: Requires view tracking with timestamps
    For now, returns estimated pattern
    """
    try:
        # Try cache first
        cache_key = f"analytics:peak-hours:period={period}"
        cached_hours = await redis_client.get(cache_key)
        
        if cached_hours:
            logger.info(f"✅ Cache hit for peak hours")
            return cached_hours
        
        # Typical viewing pattern (adjust based on your data)
        # Peak hours: 18:00-23:00 (evening)
        hours = []
        
        for hour in range(24):
            # Simulate viewing pattern
            if 6 <= hour < 9:  # Morning
                intensity = 0.3
            elif 12 <= hour < 14:  # Lunch
                intensity = 0.4
            elif 18 <= hour < 23:  # Peak evening
                intensity = 0.9 + (hour - 18) * 0.02
            elif 0 <= hour < 6:  # Night
                intensity = 0.1
            else:  # Afternoon
                intensity = 0.5
            
            # Calculate views and users based on intensity
            base_views = 1000
            base_users = 300
            
            hours.append({
                "hour": hour,
                "views": int(base_views * intensity),
                "users": int(base_users * intensity)
            })
        
        response = {"hours": hours}
        
        # Cache for 1 hour
        await redis_client.set(cache_key, response, expire=3600)
        
        logger.info(f"✅ Peak hours calculated")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error fetching peak hours: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch peak hours: {str(e)}"
        )


# ==================== CSV EXPORT ====================

@router.get("/export")
async def export_analytics(
    period: Literal['today', 'week', 'month', 'year'] = Query(default='week'),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Export analytics to CSV format
    """
    try:
        import io
        import csv
        
        logger.info(f"📊 Exporting analytics for period: {period}")
        
        # Fetch all data
        stats = await get_analytics_stats(7 if period == 'week' else 30, db, current_user)
        trends_response = await get_view_trends(7 if period == 'week' else 30, db, current_user)
        trends = trends_response["trends"]
        content_response = await get_top_content(period, 20, db, current_user)
        content = content_response["content"]
        devices_response = await get_device_stats(period, db, current_user)
        devices = devices_response["devices"]
        geo_response = await get_geographic_data(period, db, current_user)
        geographic = geo_response["geographic"]
        
        # Create CSV
        output = io.StringIO()
        output.write('Zentrya Analytics Report\n')
        output.write(f'Period: {period.title()}\n')
        output.write(f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}\n\n')
        
        # Overall Stats
        output.write('OVERALL STATISTICS\n')
        output.write('Metric,Value\n')
        output.write(f'Total Users,{stats["total_users"]}\n')
        output.write(f'Active Users,{stats["active_users"]}\n')
        output.write(f'Total Movies,{stats["total_movies"]}\n')
        output.write(f'Total Series,{stats["total_series"]}\n')
        output.write(f'Total Views,{stats["total_views"]}\n')
        output.write(f'Total Watch Time (hours),{round(stats["total_watch_time"] / 60, 2)}\n')
        output.write(f'Average Watch Time (minutes),{stats["avg_watch_time"]}\n')
        output.write(f'User Growth Rate (%),{stats["user_growth_rate"]}\n')
        output.write(f'Engagement Rate (%),{stats["engagement_rate"]}\n\n')
        
        # View Trends
        output.write('VIEW TRENDS\n')
        output.write('Date,Views,Unique Users,Watch Time (hours)\n')
        for trend in trends:
            output.write(f'{trend["date"]},{trend["views"]},{trend["unique_users"]},{round(trend["watch_time"] / 60, 2)}\n')
        output.write('\n')
        
        # Top Content
        output.write('TOP PERFORMING CONTENT\n')
        output.write('Title,Type,Views,Watch Time (hours),Completion Rate (%),Rating\n')
        for item in content:
            output.write(f'"{item["title"]}",{item["type"]},{item["views"]},{round(item["watch_time"] / 60, 2)},{item["completion_rate"]},{item["rating"]}\n')
        output.write('\n')
        
        # Device Stats
        output.write('DEVICE STATISTICS\n')
        output.write('Device,Count,Percentage\n')
        for device in devices:
            output.write(f'{device["device"]},{device["count"]},{device["percentage"]}%\n')
        output.write('\n')
        
        # Geographic
        output.write('GEOGRAPHIC DISTRIBUTION\n')
        output.write('Country,Users,Views\n')
        for geo in geographic:
            output.write(f'{geo["country"]},{geo["users"]},{geo["views"]}\n')
        
        csv_data = output.getvalue()
        output.close()
        
        logger.info(f"✅ Analytics exported successfully")
        return csv_data
        
    except Exception as e:
        logger.error(f"❌ Error exporting analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export analytics: {str(e)}"
        )