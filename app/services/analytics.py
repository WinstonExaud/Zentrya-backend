from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from ..models.view_history import ViewHistory
from ..models.movie import Movie
from ..models.series import Series
from ..models.episode import Episode
from ..models.user import User

class AnalyticsService:
    
    def get_popular_movies(self, db: Session, days: int = 30, limit: int = 10) -> List[Dict]:
        """Get most popular movies in the last N days"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        popular_movies = (
            db.query(
                Movie.id,
                Movie.title,
                Movie.poster_url,
                func.count(ViewHistory.id).label('view_count')
            )
            .join(ViewHistory)
            .filter(ViewHistory.watched_at >= start_date)
            .filter(ViewHistory.movie_id.isnot(None))
            .group_by(Movie.id, Movie.title, Movie.poster_url)
            .order_by(desc('view_count'))
            .limit(limit)
            .all()
        )
        
        return [
            {
                "id": movie.id,
                "title": movie.title,
                "poster_url": movie.poster_url,
                "view_count": movie.view_count
            }
            for movie in popular_movies
        ]

    def get_popular_series(self, db: Session, days: int = 30, limit: int = 10) -> List[Dict]:
        """Get most popular series in the last N days"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        popular_series = (
            db.query(
                Series.id,
                Series.title,
                Series.poster_url,
                func.count(ViewHistory.id).label('view_count')
            )
            .join(Episode, Series.id == Episode.series_id)
            .join(ViewHistory, Episode.id == ViewHistory.episode_id)
            .filter(ViewHistory.watched_at >= start_date)
            .group_by(Series.id, Series.title, Series.poster_url)
            .order_by(desc('view_count'))
            .limit(limit)
            .all()
        )
        
        return [
            {
                "id": series.id,
                "title": series.title,
                "poster_url": series.poster_url,
                "view_count": series.view_count
            }
            for series in popular_series
        ]

    def get_user_activity_stats(self, db: Session, days: int = 30) -> Dict:
        """Get user activity statistics"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Active users in period
        active_users = (
            db.query(func.count(func.distinct(ViewHistory.user_id)))
            .filter(ViewHistory.watched_at >= start_date)
            .scalar()
        )
        
        # Total watch time in hours
        total_watch_time = (
            db.query(func.sum(ViewHistory.watch_duration))
            .filter(ViewHistory.watched_at >= start_date)
            .scalar() or 0
        ) / 3600  # Convert to hours
        
        # Average session duration
        avg_session_duration = (
            db.query(func.avg(ViewHistory.watch_duration))
            .filter(ViewHistory.watched_at >= start_date)
            .scalar() or 0
        ) / 60  # Convert to minutes
        
        return {
            "active_users": active_users,
            "total_watch_time_hours": round(total_watch_time, 2),
            "average_session_minutes": round(avg_session_duration, 2),
            "period_days": days
        }

    def get_content_completion_rates(self, db: Session, days: int = 30) -> Dict:
        """Get content completion rates"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Movies with completion rate > 80%
        completed_movies = (
            db.query(func.count(ViewHistory.id))
            .filter(ViewHistory.watched_at >= start_date)
            .filter(ViewHistory.movie_id.isnot(None))
            .filter(ViewHistory.progress_percentage >= 80)
            .scalar()
        )
        
        total_movie_views = (
            db.query(func.count(ViewHistory.id))
            .filter(ViewHistory.watched_at >= start_date)
            .filter(ViewHistory.movie_id.isnot(None))
            .scalar()
        )
        
        # Episodes with completion rate > 80%
        completed_episodes = (
            db.query(func.count(ViewHistory.id))
            .filter(ViewHistory.watched_at >= start_date)
            .filter(ViewHistory.episode_id.isnot(None))
            .filter(ViewHistory.progress_percentage >= 80)
            .scalar()
        )
        
        total_episode_views = (
            db.query(func.count(ViewHistory.id))
            .filter(ViewHistory.watched_at >= start_date)
            .filter(ViewHistory.episode_id.isnot(None))
            .scalar()
        )
        
        movie_completion_rate = (completed_movies / total_movie_views * 100) if total_movie_views > 0 else 0
        episode_completion_rate = (completed_episodes / total_episode_views * 100) if total_episode_views > 0 else 0
        
        return {
            "movie_completion_rate": round(movie_completion_rate, 2),
            "episode_completion_rate": round(episode_completion_rate, 2),
            "total_movie_views": total_movie_views,
            "total_episode_views": total_episode_views
        }

    def get_daily_usage_stats(self, db: Session, days: int = 7) -> List[Dict]:
        """Get daily usage statistics"""
        daily_stats = []
        
        for i in range(days):
            date = datetime.utcnow().date() - timedelta(days=i)
            start_date = datetime.combine(date, datetime.min.time())
            end_date = start_date + timedelta(days=1)
            
            views = (
                db.query(func.count(ViewHistory.id))
                .filter(ViewHistory.watched_at >= start_date)
                .filter(ViewHistory.watched_at < end_date)
                .scalar()
            )
            
            unique_users = (
                db.query(func.count(func.distinct(ViewHistory.user_id)))
                .filter(ViewHistory.watched_at >= start_date)
                .filter(ViewHistory.watched_at < end_date)
                .scalar()
            )
            
            watch_time = (
                db.query(func.sum(ViewHistory.watch_duration))
                .filter(ViewHistory.watched_at >= start_date)
                .filter(ViewHistory.watched_at < end_date)
                .scalar() or 0
            ) / 3600  # Convert to hours
            
            daily_stats.append({
                "date": date.isoformat(),
                "total_views": views,
                "unique_users": unique_users,
                "watch_time_hours": round(watch_time, 2)
            })
        
        return list(reversed(daily_stats))  # Most recent first

analytics_service = AnalyticsService()