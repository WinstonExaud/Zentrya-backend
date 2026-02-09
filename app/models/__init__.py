from app.database import Base
from app.models.user import User
from app.models.category import Category
from app.models.genre import Genre
from app.models.movie import Movie, movie_genres
from app.models.series import Series, series_genres, Episode
from app.models.watch_analytics import WatchSession, MovieAnalytics, SeriesAnalytics, EpisodeAnalytics
from app.models.watch_progress import WatchProgress

# This ensures all models are registered with Base.metadata
__all__ = [
    "Base", "User", "Category", "Genre", "Movie", "Series", 
    "Episode", "series_genres", "movie_genres", "WatchSession", 
    "MovieAnalytics", "SeriesAnalytics", "EpisodeAnalytics", "WatchProgress"
]