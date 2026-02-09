"""
Zentrya Watch-Time Tracking Service
Handles view tracking, watch-time calculation, and fraud prevention
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ..models import Movie, User, Series, Episode, WatchSession, MovieAnalytics, SeriesAnalytics, EpisodeAnalytics
from ..redis_client import redis_client

logger = logging.getLogger(__name__)


class WatchTimeService:
    """
    Netflix-grade watch-time tracking with fraud prevention
    """
    
    # Rewatch weight configuration
    REWATCH_WEIGHTS = {
        'day_2': 0.50,      # 50% value for day 2 rewatch
        'day_3_plus': 0.30,  # 30% value for day 3+ rewatches
        'same_day': 0.0      # 0% for same-day abuse
    }
    
    COMPLETION_THRESHOLD = 0.90  # 90% = completed
    
    
    async def start_watch_session(
        self,
        db: AsyncSession,
        user_id: int,
        movie_id: int,
        video_duration: int,
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a new watch session
        
        Returns:
            session_id: Unique session identifier
            is_first_watch: True if this is user's first watch
            view_counted: True if this incremented the view count
        """
        try:
            # Check if this is first watch for this user+movie
            result = await db.execute(
                select(WatchSession)
                .where(
                    and_(
                        WatchSession.user_id == user_id,
                        WatchSession.movie_id == movie_id
                    )
                )
                .order_by(WatchSession.started_at.desc())
                .limit(1)
            )
            previous_session = result.scalar_one_or_none()
            
            is_first_watch = previous_session is None
            view_counted = False
            
            # Generate session ID
            session_id = f"watch_{uuid.uuid4()}"
            
            # Create new session
            session = WatchSession(
                session_id=session_id,
                user_id=user_id,
                movie_id=movie_id,
                video_duration_seconds=video_duration,
                is_first_watch=is_first_watch,
                device_id=device_id
            )
            
            db.add(session)
            await db.commit()
            await db.refresh(session)
            
            # Increment view count ONLY on first watch
            if is_first_watch:
                await db.execute(
                    Movie.__table__.update()
                    .where(Movie.id == movie_id)
                    .values(view_count=Movie.view_count + 1)
                )
                await db.commit()
                view_counted = True
                
                logger.info(f"✅ NEW VIEW: User {user_id} → Movie {movie_id}")
            else:
                logger.info(f"🔄 REWATCH: User {user_id} → Movie {movie_id}")
            
            # Cache session in Redis for fast updates
            await redis_client.set(
                f"watch:session:{session_id}",
                {
                    'user_id': user_id,
                    'movie_id': movie_id,
                    'started_at': session.started_at.isoformat(),
                    'watch_time': 0,
                    'is_first_watch': is_first_watch
                },
                expire=86400  # 24 hours
            )
            
            return {
                'session_id': session_id,
                'is_first_watch': is_first_watch,
                'view_counted': view_counted,
                'started_at': session.started_at.isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Error starting watch session: {e}")
            raise
    
    
    async def update_watch_progress(
        self,
        db: AsyncSession,
        session_id: str,
        current_position_seconds: int,
        quality_level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update watch progress during playback
        Called periodically (every 10-30 seconds)
        """
        try:
            # Get session from Redis first (fast)
            cached_session = await redis_client.get(f"watch:session:{session_id}")
            
            if not cached_session:
                # Fallback to database
                result = await db.execute(
                    select(WatchSession)
                    .where(WatchSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()
                
                if not session:
                    raise ValueError(f"Session {session_id} not found")
            else:
                # Get full session from DB for update
                result = await db.execute(
                    select(WatchSession)
                    .where(WatchSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()
            
            # Update watch time
            session.watch_time_seconds = max(session.watch_time_seconds, current_position_seconds)
            session.completion_percentage = (current_position_seconds / session.video_duration_seconds) * 100
            session.last_position_update = datetime.utcnow()
            
            if quality_level:
                session.quality_level = quality_level
            
            # Check if completed
            if session.completion_percentage >= (self.COMPLETION_THRESHOLD * 100):
                session.is_completed = True
                if not session.completed_at:
                    session.completed_at = datetime.utcnow()
            
            await db.commit()
            
            # Update Redis cache
            await redis_client.set(
                f"watch:session:{session_id}",
                {
                    'user_id': session.user_id,
                    'movie_id': session.movie_id,
                    'started_at': session.started_at.isoformat(),
                    'watch_time': session.watch_time_seconds,
                    'is_first_watch': session.is_first_watch,
                    'completion': session.completion_percentage
                },
                expire=86400
            )
            
            return {
                'session_id': session_id,
                'watch_time_seconds': session.watch_time_seconds,
                'completion_percentage': round(session.completion_percentage, 2),
                'is_completed': session.is_completed
            }
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Error updating watch progress: {e}")
            raise
    
    
    async def end_watch_session(
        self,
        db: AsyncSession,
        session_id: str
    ) -> Dict[str, Any]:
        """
        End watch session and calculate contribution
        """
        try:
            result = await db.execute(
                select(WatchSession)
                .where(WatchSession.session_id == session_id)
            )
            session = result.scalar_one_or_none()
            
            if not session:
                raise ValueError(f"Session {session_id} not found")
            
            # Calculate effective watch time
            watch_time_minutes = session.watch_time_seconds / 60
            
            # Apply rewatch penalty if needed
            if not session.is_first_watch:
                days_since_first = await self._get_days_since_first_watch(
                    db, session.user_id, session.movie_id
                )
                
                if days_since_first == 0:
                    # Same day = fraud
                    effective_minutes = 0
                    weight = self.REWATCH_WEIGHTS['same_day']
                elif days_since_first == 1:
                    # Day 2 = 50%
                    effective_minutes = watch_time_minutes * self.REWATCH_WEIGHTS['day_2']
                    weight = self.REWATCH_WEIGHTS['day_2']
                else:
                    # Day 3+ = 30%
                    effective_minutes = watch_time_minutes * self.REWATCH_WEIGHTS['day_3_plus']
                    weight = self.REWATCH_WEIGHTS['day_3_plus']
            else:
                # First watch = 100%
                effective_minutes = watch_time_minutes
                weight = 1.0
            
            logger.info(
                f"📊 Session ended: {session_id[:16]}... | "
                f"Watch: {watch_time_minutes:.1f}min | "
                f"Effective: {effective_minutes:.1f}min | "
                f"Weight: {weight*100:.0f}% | "
                f"First: {session.is_first_watch}"
            )
            
            # Queue analytics update
            await self._queue_analytics_update(
                session.movie_id,
                watch_time_minutes,
                effective_minutes,
                session.is_first_watch,
                session.is_completed
            )
            
            # Clean up Redis
            await redis_client.delete(f"watch:session:{session_id}")
            
            return {
                'session_id': session_id,
                'watch_time_minutes': round(watch_time_minutes, 2),
                'effective_watch_time_minutes': round(effective_minutes, 2),
                'weight_applied': weight,
                'is_first_watch': session.is_first_watch,
                'completion_percentage': round(session.completion_percentage, 2)
            }
            
        except Exception as e:
            logger.error(f"❌ Error ending watch session: {e}")
            raise
    
    
    async def get_movie_analytics(
        self,
        db: AsyncSession,
        movie_id: int
    ) -> Dict[str, Any]:
        """
        Get aggregated analytics for a movie
        """
        try:
            result = await db.execute(
                select(MovieAnalytics)
                .where(MovieAnalytics.movie_id == movie_id)
            )
            analytics = result.scalar_one_or_none()
            
            if not analytics:
                # Initialize analytics if not exists
                analytics = MovieAnalytics(movie_id=movie_id)
                db.add(analytics)
                await db.commit()
                await db.refresh(analytics)
            
            return {
                'movie_id': movie_id,
                'views': {
                    'total_views': analytics.total_views,
                    'rewatched_views': analytics.rewatched_views,
                    'unique_viewers': analytics.unique_viewers
                },
                'watch_time': {
                    'actual_watch_time_minutes': round(analytics.actual_watch_time_minutes, 2),
                    'rewatched_watch_time_minutes': round(analytics.rewatched_watch_time_minutes, 2),
                    'effective_watch_time_minutes': round(analytics.effective_watch_time_minutes, 2)
                },
                'engagement': {
                    'average_completion_rate': round(analytics.average_completion_rate, 2),
                    'total_sessions': analytics.total_sessions,
                    'most_watched_quality': analytics.most_watched_quality
                },
                'payment': {
                    'last_payment_month': analytics.last_payment_month,
                    'monthly_earnings_tzs': analytics.monthly_earnings_tzs
                },
                'last_updated': analytics.last_updated.isoformat() if analytics.last_updated else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting movie analytics: {e}")
            raise
    
    
    async def _get_days_since_first_watch(
        self,
        db: AsyncSession,
        user_id: int,
        movie_id: int
    ) -> int:
        """
        Get days since user's first watch of this movie
        """
        try:
            result = await db.execute(
                select(WatchSession.started_at)
                .where(
                    and_(
                        WatchSession.user_id == user_id,
                        WatchSession.movie_id == movie_id,
                        WatchSession.is_first_watch == True
                    )
                )
                .order_by(WatchSession.started_at.asc())
                .limit(1)
            )
            first_watch_time = result.scalar_one_or_none()
            
            if not first_watch_time:
                return 0
            
            days = (datetime.utcnow() - first_watch_time).days
            return days
            
        except Exception as e:
            logger.error(f"❌ Error calculating days since first watch: {e}")
            return 0
    
    
    async def _queue_analytics_update(
        self,
        movie_id: int,
        watch_time_minutes: float,
        effective_minutes: float,
        is_first_watch: bool,
        is_completed: bool
    ):
        """
        Queue analytics update in Redis for batch processing
        """
        try:
            update_key = f"analytics:queue:{movie_id}"
            
            current_queue = await redis_client.get(update_key) or {
                'pending_actual': 0,
                'pending_rewatched': 0,
                'pending_effective': 0,
                'pending_sessions': 0,
                'pending_completions': 0
            }
            
            if is_first_watch:
                current_queue['pending_actual'] += watch_time_minutes
            else:
                current_queue['pending_rewatched'] += watch_time_minutes
            
            current_queue['pending_effective'] += effective_minutes
            current_queue['pending_sessions'] += 1
            
            if is_completed:
                current_queue['pending_completions'] += 1
            
            await redis_client.set(update_key, current_queue, expire=3600)
            
        except Exception as e:
            logger.error(f"❌ Error queuing analytics update: {e}")


    
    # ==================== SERIES & EPISODE METHODS ====================
    
    async def start_episode_watch_session(
        self,
        db: AsyncSession,
        user_id: int,
        series_id: int,
        episode_id: int,
        video_duration: int,
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start watch session for an episode
        
        Key Differences from Movies:
        - Series view counted on FIRST episode watch only
        - Each episode tracked separately
        - Episode watch-time rolls up to series
        
        Returns:
            session_id: Unique session identifier
            is_first_episode_watch: True if user's first watch of THIS episode
            is_first_series_watch: True if user's first watch of ANY episode in series
            series_view_counted: True if series view was incremented
        """
        try:
            # Check if this is first watch of THIS episode
            result = await db.execute(
                select(WatchSession)
                .where(
                    and_(
                        WatchSession.user_id == user_id,
                        WatchSession.episode_id == episode_id
                    )
                )
                .order_by(WatchSession.started_at.desc())
                .limit(1)
            )
            previous_episode_session = result.scalar_one_or_none()
            
            is_first_episode_watch = previous_episode_session is None
            
            # Check if this is first watch of ANY episode in series
            result = await db.execute(
                select(WatchSession)
                .where(
                    and_(
                        WatchSession.user_id == user_id,
                        WatchSession.series_id == series_id
                    )
                )
                .limit(1)
            )
            previous_series_session = result.scalar_one_or_none()
            
            is_first_series_watch = previous_series_session is None
            series_view_counted = False
            
            # Generate session ID
            session_id = f"watch_{uuid.uuid4()}"
            
            # Create new session
            session = WatchSession(
                session_id=session_id,
                user_id=user_id,
                series_id=series_id,
                episode_id=episode_id,
                movie_id=None,
                video_duration_seconds=video_duration,
                is_first_watch=is_first_episode_watch,
                device_id=device_id
            )
            
            db.add(session)
            await db.commit()
            await db.refresh(session)
            
            # Increment SERIES view count ONLY on first series watch
            if is_first_series_watch:
                await db.execute(
                    Series.__table__.update()
                    .where(Series.id == series_id)
                    .values(view_count=Series.view_count + 1)
                )
                await db.commit()
                series_view_counted = True
                
                logger.info(f"✅ NEW SERIES VIEW: User {user_id} → Series {series_id}")
            
            # Always increment EPISODE view count on first episode watch (for insights)
            if is_first_episode_watch:
                await db.execute(
                    Episode.__table__.update()
                    .where(Episode.id == episode_id)
                    .values(view_count=Episode.view_count + 1)
                )
                await db.commit()
                logger.info(f"📺 NEW EPISODE WATCH: User {user_id} → Episode {episode_id}")
            else:
                logger.info(f"🔄 EPISODE REWATCH: User {user_id} → Episode {episode_id}")
            
            # Cache session in Redis
            await redis_client.set(
                f"watch:session:{session_id}",
                {
                    'user_id': user_id,
                    'series_id': series_id,
                    'episode_id': episode_id,
                    'started_at': session.started_at.isoformat(),
                    'watch_time': 0,
                    'is_first_watch': is_first_episode_watch
                },
                expire=86400  # 24 hours
            )
            
            return {
                'session_id': session_id,
                'is_first_episode_watch': is_first_episode_watch,
                'is_first_series_watch': is_first_series_watch,
                'series_view_counted': series_view_counted,
                'started_at': session.started_at.isoformat()
            }
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Error starting episode watch session: {e}")
            raise
    
    
    async def get_series_analytics(
        self,
        db: AsyncSession,
        series_id: int
    ) -> Dict[str, Any]:
        """
        Get aggregated analytics for a series
        
        Includes:
        - Series-level views and watch-time
        - Episode-by-episode breakdown
        - Drop-off analysis
        - Binge-watching metrics
        """
        try:
            # Get series analytics
            result = await db.execute(
                select(SeriesAnalytics)
                .where(SeriesAnalytics.series_id == series_id)
            )
            analytics = result.scalar_one_or_none()
            
            if not analytics:
                # Initialize analytics if not exists
                analytics = SeriesAnalytics(series_id=series_id)
                db.add(analytics)
                await db.commit()
                await db.refresh(analytics)
            
            # Get episode-by-episode analytics
            result = await db.execute(
                select(EpisodeAnalytics, Episode)
                .join(Episode, EpisodeAnalytics.episode_id == Episode.id)
                .where(EpisodeAnalytics.series_id == series_id)
                .order_by(Episode.season_number, Episode.episode_number)
            )
            episode_analytics_list = result.all()
            
            episodes_breakdown = []
            for ep_analytics, episode in episode_analytics_list:
                episodes_breakdown.append({
                    "episode_id": episode.id,
                    "season_number": episode.season_number,
                    "episode_number": episode.episode_number,
                    "episode_code": f"S{episode.season_number:02d}E{episode.episode_number:02d}",
                    "title": episode.title,
                    "effective_watch_time_minutes": round(ep_analytics.effective_watch_time_minutes, 2),
                    "completion_rate": round(ep_analytics.completion_rate, 2),
                    "unique_viewers": ep_analytics.unique_viewers,
                    "total_starts": ep_analytics.total_starts,
                    "total_completions": ep_analytics.total_completions,
                })
            
            return {
                'series_id': series_id,
                'views': {
                    'total_views': analytics.total_views,
                    'rewatched_views': analytics.rewatched_views,
                    'unique_viewers': analytics.unique_viewers
                },
                'watch_time': {
                    'actual_watch_time_minutes': round(analytics.actual_watch_time_minutes, 2),
                    'rewatched_watch_time_minutes': round(analytics.rewatched_watch_time_minutes, 2),
                    'effective_watch_time_minutes': round(analytics.effective_watch_time_minutes, 2)
                },
                'engagement': {
                    'average_completion_rate': round(analytics.average_completion_rate, 2),
                    'average_episodes_per_viewer': round(analytics.average_episodes_per_viewer, 2),
                    'binge_rate': round(analytics.binge_rate, 2),
                    'drop_off_episode': analytics.drop_off_episode,
                    'total_sessions': analytics.total_sessions,
                    'total_episodes_watched': analytics.total_episodes_watched,
                },
                'payment': {
                    'last_payment_month': analytics.last_payment_month,
                    'monthly_earnings_tzs': analytics.monthly_earnings_tzs
                },
                'episodes_breakdown': episodes_breakdown,
                'last_updated': analytics.last_updated.isoformat() if analytics.last_updated else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting series analytics: {e}")
            raise
    
    
    async def get_episode_analytics(
        self,
        db: AsyncSession,
        episode_id: int
    ) -> Dict[str, Any]:
        """
        Get detailed analytics for a single episode
        
        Used for:
        - Drop-off analysis
        - Quality improvements
        - Identifying problematic content
        """
        try:
            result = await db.execute(
                select(EpisodeAnalytics)
                .where(EpisodeAnalytics.episode_id == episode_id)
            )
            analytics = result.scalar_one_or_none()
            
            if not analytics:
                # Initialize analytics if not exists
                result = await db.execute(
                    select(Episode).where(Episode.id == episode_id)
                )
                episode = result.scalar_one_or_none()
                
                if not episode:
                    raise ValueError(f"Episode {episode_id} not found")
                
                analytics = EpisodeAnalytics(
                    episode_id=episode_id,
                    series_id=episode.series_id
                )
                db.add(analytics)
                await db.commit()
                await db.refresh(analytics)
            
            return {
                'episode_id': episode_id,
                'series_id': analytics.series_id,
                'watch_time': {
                    'actual_watch_time_minutes': round(analytics.actual_watch_time_minutes, 2),
                    'rewatched_watch_time_minutes': round(analytics.rewatched_watch_time_minutes, 2),
                    'effective_watch_time_minutes': round(analytics.effective_watch_time_minutes, 2)
                },
                'engagement': {
                    'total_starts': analytics.total_starts,
                    'total_completions': analytics.total_completions,
                    'completion_rate': round(analytics.completion_rate, 2),
                    'average_watch_percentage': round(analytics.average_watch_percentage, 2),
                    'unique_viewers': analytics.unique_viewers,
                    'total_sessions': analytics.total_sessions,
                    'average_rewatch_count': round(analytics.average_rewatch_count, 2)
                },
                'drop_off_analysis': {
                    'drop_off_at_25': analytics.drop_off_at_25,
                    'drop_off_at_50': analytics.drop_off_at_50,
                    'drop_off_at_75': analytics.drop_off_at_75
                },
                'quality': {
                    'most_watched_quality': analytics.most_watched_quality
                },
                'last_updated': analytics.last_updated.isoformat() if analytics.last_updated else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting episode analytics: {e}")
            raise


# Singleton instance
watch_time_service = WatchTimeService()