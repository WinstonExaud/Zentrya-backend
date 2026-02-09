"""
Zentrya Analytics Background Processor
Batch-processes watch sessions into aggregated analytics
Run as a scheduled job (every 5-15 minutes)
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update

from ..database import AsyncSessionLocal
from ..models import Movie, WatchSession, MovieAnalytics
from ..redis_client import redis_client

logger = logging.getLogger(__name__)


class AnalyticsProcessor:
    """
    Background processor for aggregating watch-time analytics
    """
    
    async def process_all_queued_updates(self):
        """
        Process all queued analytics updates from Redis
        Should run every 5-15 minutes
        """
        try:
            logger.info("🔄 Starting analytics batch processing...")
            
            # Get all queued movie updates
            pattern = "analytics:queue:*"
            keys = await redis_client.keys(pattern)
            
            if not keys:
                logger.info("✅ No queued analytics updates")
                return
            
            logger.info(f"📊 Found {len(keys)} movies with pending analytics")
            
            async with AsyncSessionLocal() as db:
                for key in keys:
                    try:
                        # Extract movie_id from key
                        movie_id = int(key.split(':')[-1])
                        
                        # Get queued data
                        queued_data = await redis_client.get(key)
                        
                        if not queued_data:
                            continue
                        
                        # Update analytics
                        await self._update_movie_analytics(
                            db,
                            movie_id,
                            queued_data
                        )
                        
                        # Clear queue
                        await redis_client.delete(key)
                        
                    except Exception as e:
                        logger.error(f"❌ Error processing analytics for key {key}: {e}")
                        continue
                
                await db.commit()
            
            logger.info(f"✅ Batch processing completed: {len(keys)} movies updated")
            
        except Exception as e:
            logger.error(f"❌ Error in analytics batch processing: {e}")
    
    
    async def _update_movie_analytics(
        self,
        db: AsyncSession,
        movie_id: int,
        queued_data: Dict
    ):
        """
        Update analytics for a single movie
        """
        try:
            # Get or create analytics record
            result = await db.execute(
                select(MovieAnalytics).where(MovieAnalytics.movie_id == movie_id)
            )
            analytics = result.scalar_one_or_none()
            
            if not analytics:
                analytics = MovieAnalytics(movie_id=movie_id)
                db.add(analytics)
            
            # Apply queued updates
            analytics.actual_watch_time_minutes += queued_data.get('pending_actual', 0)
            analytics.rewatched_watch_time_minutes += queued_data.get('pending_rewatched', 0)
            analytics.effective_watch_time_minutes += queued_data.get('pending_effective', 0)
            analytics.total_sessions += queued_data.get('pending_sessions', 0)
            
            # Recalculate views from watch_sessions
            views_result = await db.execute(
                select(
                    func.count(func.distinct(WatchSession.user_id)),
                    func.count(WatchSession.id).filter(WatchSession.is_first_watch == False)
                )
                .where(WatchSession.movie_id == movie_id)
            )
            unique_viewers, rewatched_count = views_result.one()
            
            analytics.total_views = unique_viewers
            analytics.unique_viewers = unique_viewers
            analytics.rewatched_views = rewatched_count
            
            # Calculate average completion rate
            completion_result = await db.execute(
                select(func.avg(WatchSession.completion_percentage))
                .where(WatchSession.movie_id == movie_id)
            )
            avg_completion = completion_result.scalar() or 0
            analytics.average_completion_rate = avg_completion
            
            # Most watched quality
            quality_result = await db.execute(
                select(
                    WatchSession.quality_level,
                    func.count(WatchSession.id)
                )
                .where(
                    and_(
                        WatchSession.movie_id == movie_id,
                        WatchSession.quality_level.isnot(None)
                    )
                )
                .group_by(WatchSession.quality_level)
                .order_by(func.count(WatchSession.id).desc())
                .limit(1)
            )
            quality_row = quality_result.one_or_none()
            
            if quality_row:
                analytics.most_watched_quality = quality_row[0]
            
            analytics.last_updated = datetime.utcnow()
            
            logger.info(
                f"✅ Analytics updated for movie {movie_id}: "
                f"Views={analytics.total_views}, "
                f"Effective Time={analytics.effective_watch_time_minutes:.1f}min"
            )
            
        except Exception as e:
            logger.error(f"❌ Error updating analytics for movie {movie_id}: {e}")
            raise
    
    
    async def calculate_monthly_payments(
        self,
        month: str,  # Format: "YYYY-MM"
        subscription_revenue_tzs: float
    ):
        """
        Calculate monthly producer payments
        
        Args:
            month: Payment month (e.g., "2025-02")
            subscription_revenue_tzs: Total subscription revenue for the month
        
        Formula:
            Producer Pay = (Producer Effective Watch Time ÷ Platform Total Watch Time) × Producers Pool
        """
        try:
            logger.info(f"💰 Calculating payments for {month}")
            logger.info(f"📊 Total subscription revenue: {subscription_revenue_tzs:,.0f} TZS")
            
            # Calculate producers pool (60% of revenue)
            producers_pool = subscription_revenue_tzs * 0.60
            
            logger.info(f"💵 Producers pool (60%): {producers_pool:,.0f} TZS")
            
            async with AsyncSessionLocal() as db:
                # Get all movies with analytics
                result = await db.execute(
                    select(MovieAnalytics, Movie)
                    .join(Movie, MovieAnalytics.movie_id == Movie.id)
                    .where(MovieAnalytics.effective_watch_time_minutes > 0)
                )
                analytics_records = result.all()
                
                if not analytics_records:
                    logger.warning("⚠️ No movies with watch-time found")
                    return
                
                # Calculate platform total watch time
                platform_total_minutes = sum(
                    a.MovieAnalytics.effective_watch_time_minutes
                    for a in analytics_records
                )
                
                logger.info(f"🌐 Platform total effective watch time: {platform_total_minutes:,.1f} minutes")
                
                # Group by producer
                producer_data = {}
                
                for record in analytics_records:
                    analytics, movie = record.MovieAnalytics, record.Movie
                    
                    # Get producer (assuming movie.user_id is the producer)
                    producer_id = movie.user_id if hasattr(movie, 'user_id') else None
                    
                    if not producer_id:
                        continue
                    
                    if producer_id not in producer_data:
                        producer_data[producer_id] = {
                            'effective_watch_time': 0,
                            'actual_watch_time': 0,
                            'rewatched_watch_time': 0,
                            'movie_count': 0
                        }
                    
                    producer_data[producer_id]['effective_watch_time'] += analytics.effective_watch_time_minutes
                    producer_data[producer_id]['actual_watch_time'] += analytics.actual_watch_time_minutes
                    producer_data[producer_id]['rewatched_watch_time'] += analytics.rewatched_watch_time_minutes
                    producer_data[producer_id]['movie_count'] += 1
                
                # Calculate individual payments
                logger.info(f"👥 Calculating payments for {len(producer_data)} producers")
                
                year, month_num = month.split('-')
                
                for producer_id, data in producer_data.items():
                    effective_time = data['effective_watch_time']
                    
                    # Calculate payment
                    payment_percentage = effective_time / platform_total_minutes
                    payment_amount = producers_pool * payment_percentage
                    
                    logger.info(
                        f"  Producer {producer_id}: "
                        f"{effective_time:,.1f} min ({payment_percentage*100:.2f}%) = "
                        f"{payment_amount:,.0f} TZS"
                    )
                    
                    # Store payment record
                    from ..models.watch_analytics import MonthlyPayment
                    
                    # Check if payment already exists
                    existing = await db.execute(
                        select(MonthlyPayment).where(
                            and_(
                                MonthlyPayment.producer_id == producer_id,
                                MonthlyPayment.month == month
                            )
                        )
                    )
                    payment_record = existing.scalar_one_or_none()
                    
                    if payment_record:
                        # Update existing
                        payment_record.effective_watch_time_minutes = effective_time
                        payment_record.actual_watch_time_minutes = data['actual_watch_time']
                        payment_record.rewatched_watch_time_minutes = data['rewatched_watch_time']
                        payment_record.platform_total_watch_time = platform_total_minutes
                        payment_record.producers_pool_tzs = producers_pool
                        payment_record.payment_percentage = payment_percentage
                        payment_record.payment_amount_tzs = payment_amount
                        payment_record.total_movies = data['movie_count']
                    else:
                        # Create new
                        payment_record = MonthlyPayment(
                            month=month,
                            year=int(year),
                            month_number=int(month_num),
                            producer_id=producer_id,
                            producer_name=f"Producer {producer_id}",  # Update with actual name
                            total_movies=data['movie_count'],
                            effective_watch_time_minutes=effective_time,
                            actual_watch_time_minutes=data['actual_watch_time'],
                            rewatched_watch_time_minutes=data['rewatched_watch_time'],
                            platform_total_watch_time=platform_total_minutes,
                            producers_pool_tzs=producers_pool,
                            payment_percentage=payment_percentage,
                            payment_amount_tzs=payment_amount,
                            payment_status='pending'
                        )
                        db.add(payment_record)
                
                await db.commit()
                
                logger.info(f"✅ Monthly payment calculation completed for {month}")
                
        except Exception as e:
            logger.error(f"❌ Error calculating monthly payments: {e}")
            raise


# Singleton instance
analytics_processor = AnalyticsProcessor()


# ==================== SCHEDULED JOB RUNNER ====================

async def run_analytics_processor():
    """
    Run analytics processor (call from scheduler)
    """
    await analytics_processor.process_all_queued_updates()


async def run_monthly_payment_calculation(month: str, revenue: float):
    """
    Run monthly payment calculation
    """
    await analytics_processor.calculate_monthly_payments(month, revenue)


# ==================== CLI COMMANDS ====================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "process":
            # Process queued analytics
            asyncio.run(run_analytics_processor())
        elif sys.argv[1] == "payments":
            # Calculate payments
            month = sys.argv[2] if len(sys.argv) > 2 else "2025-02"
            revenue = float(sys.argv[3]) if len(sys.argv) > 3 else 300000000
            asyncio.run(run_monthly_payment_calculation(month, revenue))
    else:
        print("Usage:")
        print("  python -m app.services.analytics_processor process")
        print("  python -m app.services.analytics_processor payments 2025-02 300000000")