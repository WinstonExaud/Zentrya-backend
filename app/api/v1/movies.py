from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import Movie, Genre, Category
from ...utils.storage import storage_service
import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/movies", tags=["movies"])


# Pydantic models
class MovieCreate(BaseModel):
    title: str
    slug: str
    description: str
    synopsis: Optional[str] = None
    duration: Optional[int] = None
    release_year: Optional[int] = None
    rating: float = 0
    content_rating: Optional[str] = None
    language: str = "English"
    director: Optional[str] = None
    production: Optional[str] = None
    cast: Optional[List[str]] = None
    category_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    is_featured: bool = False
    is_active: bool = False


class MovieUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    synopsis: Optional[str] = None
    duration: Optional[int] = None
    release_year: Optional[int] = None
    rating: Optional[float] = None
    content_rating: Optional[str] = None
    language: Optional[str] = None
    director: Optional[str] = None
    production: Optional[str] = None
    category_id: Optional[int] = None
    genre_ids: Optional[List[int]] = None
    cast: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None


def format_movie(movie: Movie, db: Session) -> dict:
    """Helper function to format movie with category name"""
    category_name = None
    if movie.category_id:
        category = db.query(Category).filter(Category.id == movie.category_id).first()
        category_name = category.name if category else None
    
    return {
        "id": movie.id,
        "title": movie.title,
        "slug": movie.slug,
        "description": movie.description,
        "synopsis": movie.synopsis,
        "poster_url": movie.poster_url,
        "banner_url": movie.banner_url,
        "trailer_url": movie.trailer_url,
        "video_url": movie.video_url,
        "duration": movie.duration,
        "release_year": movie.release_year,
        "rating": movie.rating,
        "content_rating": movie.content_rating,
        "language": movie.language,
        "director": movie.director,
        "production": movie.production,
        "cast": movie.cast,
        "view_count": movie.view_count,
        "category_id": movie.category_id,
        "category_name": category_name,
        "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
        "is_active": movie.is_active,
        "is_featured": movie.is_featured,
        "created_at": movie.created_at.isoformat() if movie.created_at else None,
        "updated_at": movie.updated_at.isoformat() if movie.updated_at else None,
    }


@router.get("/list", status_code=status.HTTP_200_OK)
def list_movies(
    skip: int = 0,
    limit: int = 100,
    sort: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Get all movies with pagination and filtering"""
    try:
        logger.info(f"list_movies called with skip={skip}, limit={limit}, sort={sort}, is_active={is_active}")
        query = db.query(Movie)

        # Apply filters
        if is_active is not None:
            query = query.filter(Movie.is_active == is_active)

        # Get total count before pagination
        total = query.count()

        # Apply sorting
        if sort == "title":
            query = query.order_by(Movie.title)
        elif sort == "views":
            query = query.order_by(Movie.view_count.desc())
        elif sort == "rating":
            query = query.order_by(Movie.rating.desc())
        else:
            query = query.order_by(Movie.created_at.desc())

        # Apply pagination
        movies = query.offset(skip).limit(limit).all()

        return {
            "movies": [format_movie(movie, db) for movie in movies],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    except Exception as e:
        logger.error(f"Error fetching movies: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch movies")


@router.get("/{movie_id}")
def get_movie(movie_id: int, db: Session = Depends(get_db)):
    """Get single movie by ID"""
    try:
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        return {
            "data": format_movie(movie, db)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching movie {movie_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch movie")


@router.post("/{movie_id}/track-view", status_code=status.HTTP_200_OK)
def track_movie_view(movie_id: int, db: Session = Depends(get_db)):
    """Track movie view - increment view count"""
    try:
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        # Increment view count
        movie.view_count = (movie.view_count or 0) + 1
        db.commit()
        
        logger.info(f"✅ View tracked for movie: {movie.title} (Total views: {movie.view_count})")
        return {
            "data": {
                "movie_id": movie.id,
                "title": movie.title,
                "view_count": movie.view_count,
                "message": "View tracked successfully"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error tracking view for movie {movie_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to track view")


@router.post("/create-with-files", status_code=status.HTTP_201_CREATED)
async def create_movie_with_files(
    title: str = Form(...),
    slug: str = Form(...),
    description: str = Form(...),
    synopsis: Optional[str] = Form(None),
    duration: Optional[int] = Form(None),
    release_year: Optional[int] = Form(None),
    rating: float = Form(0),
    content_rating: Optional[str] = Form(None),
    language: str = Form("English"),
    director: Optional[str] = Form(None),
    production: Optional[str] = Form(None),
    cast: Optional[str] = Form(None),  # JSON string
    category_id: Optional[int] = Form(None),
    genre_ids: Optional[str] = Form(None),  # JSON string
    is_featured: bool = Form(False),
    is_active: bool = Form(False),
    # File uploads
    video_file: UploadFile = File(...),
    trailer_file: Optional[UploadFile] = File(None),
    poster_file: Optional[UploadFile] = File(None),
    banner_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Create new movie with file uploads
    - Video & Trailer → Cloudflare R2 (media.zentrya.africa)
    - Poster & Banner → Firebase Storage
    """
    try:
        # Check if slug exists
        existing = db.query(Movie).filter(Movie.slug == slug).first()
        if existing:
            raise HTTPException(status_code=400, detail="Movie slug already exists")
        
        # Parse JSON fields
        cast_list = json.loads(cast) if cast else []
        genre_ids_list = json.loads(genre_ids) if genre_ids else []
        
        # Upload video to R2 (required)
        logger.info(f"Uploading video: {video_file.filename}")
        video_storage, video_url = await storage_service.upload_file(
            video_file.file,
            video_file.filename,
            video_file.content_type or 'video/mp4',
            file_category='video'
        )
        
        # Upload trailer to R2 (optional)
        trailer_url = None
        if trailer_file:
            logger.info(f"Uploading trailer: {trailer_file.filename}")
            _, trailer_url = await storage_service.upload_file(
                trailer_file.file,
                trailer_file.filename,
                trailer_file.content_type or 'video/mp4',
                file_category='trailer'
            )
        
        # Upload poster to Firebase (optional)
        poster_url = None
        if poster_file:
            logger.info(f"Uploading poster: {poster_file.filename}")
            _, poster_url = await storage_service.upload_file(
                poster_file.file,
                poster_file.filename,
                poster_file.content_type or 'image/jpeg',
                file_category='poster'
            )
        
        # Upload banner to Firebase (optional)
        banner_url = None
        if banner_file:
            logger.info(f"Uploading banner: {banner_file.filename}")
            _, banner_url = await storage_service.upload_file(
                banner_file.file,
                banner_file.filename,
                banner_file.content_type or 'image/jpeg',
                file_category='banner'
            )
        
        # Create movie record
        movie = Movie(
            title=title,
            slug=slug,
            description=description,
            video_url=video_url,
            poster_url=poster_url,
            banner_url=banner_url,
            trailer_url=trailer_url,
            synopsis=synopsis or description[:200],
            duration=duration,
            release_year=release_year,
            rating=rating,
            content_rating=content_rating,
            language=language,
            director=director,
            production=production,
            cast=cast_list,
            category_id=category_id,
            is_featured=is_featured,
            is_active=is_active,
        )
        
        # Add genres if provided
        if genre_ids_list:
            genres = db.query(Genre).filter(Genre.id.in_(genre_ids_list)).all()
            movie.genres = genres
        
        db.add(movie)
        db.commit()
        db.refresh(movie)
        
        logger.info(f"✅ Movie created: {movie.title} (ID: {movie.id})")
        return {
            "data": {
                "id": movie.id,
                "title": movie.title,
                "video_url": video_url,
                "poster_url": poster_url,
                "banner_url": banner_url,
                "trailer_url": trailer_url,
                "message": "Movie created successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error creating movie: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create movie: {str(e)}")


@router.put("/{movie_id}")
async def update_movie(
    movie_id: int,
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    synopsis: Optional[str] = Form(None),
    duration: Optional[int] = Form(None),
    release_year: Optional[int] = Form(None),
    rating: Optional[float] = Form(None),
    content_rating: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    production: Optional[str] = Form(None),
    cast: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    genre_ids: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    is_featured: Optional[bool] = Form(None),
    # Optional file uploads
    video_file: Optional[UploadFile] = File(None),
    trailer_file: Optional[UploadFile] = File(None),
    poster_file: Optional[UploadFile] = File(None),
    banner_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Update movie with optional file replacements"""
    try:
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        # Update text fields
        if title is not None:
            movie.title = title
        if description is not None:
            movie.description = description
        if synopsis is not None:
            movie.synopsis = synopsis
        if duration is not None:
            movie.duration = duration
        if release_year is not None:
            movie.release_year = release_year
        if rating is not None:
            movie.rating = rating
        if content_rating is not None:
            movie.content_rating = content_rating
        if language is not None:
            movie.language = language
        if director is not None:
            movie.director = director
        if production is not None:
            movie.production = production
        if category_id is not None:
            movie.category_id = category_id
        if is_active is not None:
            movie.is_active = is_active
        if is_featured is not None:
            movie.is_featured = is_featured
        if cast is not None:
            movie.cast = json.loads(cast)
        
        # Update genres if provided
        if genre_ids is not None:
            genre_ids_list = json.loads(genre_ids)
            genres = db.query(Genre).filter(Genre.id.in_(genre_ids_list)).all()
            movie.genres = genres
        
        # Handle file uploads - replace old files
        if video_file:
            # Delete old video from R2
            if movie.video_url:
                await storage_service.delete_file(movie.video_url, 'r2')
            
            # Upload new video
            logger.info(f"Uploading new video: {video_file.filename}")
            _, video_url = await storage_service.upload_file(
                video_file.file,
                video_file.filename,
                video_file.content_type or 'video/mp4',
                file_category='video'
            )
            movie.video_url = video_url
        
        if trailer_file:
            # Delete old trailer from R2
            if movie.trailer_url:
                await storage_service.delete_file(movie.trailer_url, 'r2')
            
            # Upload new trailer
            logger.info(f"Uploading new trailer: {trailer_file.filename}")
            _, trailer_url = await storage_service.upload_file(
                trailer_file.file,
                trailer_file.filename,
                trailer_file.content_type or 'video/mp4',
                file_category='trailer'
            )
            movie.trailer_url = trailer_url
        
        if poster_file:
            # Delete old poster from Firebase
            if movie.poster_url:
                await storage_service.delete_file(movie.poster_url, 'firebase')
            
            # Upload new poster
            logger.info(f"Uploading new poster: {poster_file.filename}")
            _, poster_url = await storage_service.upload_file(
                poster_file.file,
                poster_file.filename,
                poster_file.content_type or 'image/jpeg',
                file_category='poster'
            )
            movie.poster_url = poster_url
        
        if banner_file:
            # Delete old banner from Firebase
            if movie.banner_url:
                await storage_service.delete_file(movie.banner_url, 'firebase')
            
            # Upload new banner
            logger.info(f"Uploading new banner: {banner_file.filename}")
            _, banner_url = await storage_service.upload_file(
                banner_file.file,
                banner_file.filename,
                banner_file.content_type or 'image/jpeg',
                file_category='banner'
            )
            movie.banner_url = banner_url
        
        db.commit()
        db.refresh(movie)
        
        logger.info(f"✅ Movie updated: {movie.title}")
        return {
            "data": {
                "id": movie.id,
                "title": movie.title,
                "message": "Movie updated successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating movie {movie_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update movie")


@router.delete("/{movie_id}")
async def delete_movie(movie_id: int, db: Session = Depends(get_db)):
    """Delete movie (soft delete via is_active) and optionally remove files"""
    try:
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        # Soft delete
        movie.is_active = False
        db.commit()
        
        # Optional: Delete files from storage (uncomment to enable hard delete)
        if movie.video_url:
            await storage_service.delete_file(movie.video_url, 'r2')
        if movie.trailer_url:
            await storage_service.delete_file(movie.trailer_url, 'r2')
        if movie.poster_url:
            await storage_service.delete_file(movie.poster_url, 'firebase')
        if movie.banner_url:
            await storage_service.delete_file(movie.banner_url, 'firebase')
        
        logger.info(f"✅ Movie soft deleted: {movie.title}")
        return {"data": {"message": "Movie deleted successfully"}}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting movie {movie_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete movie")


@router.delete("/{movie_id}/hard")
async def hard_delete_movie(movie_id: int, db: Session = Depends(get_db)):
    """
    Permanently delete movie and all associated files
    WARNING: This action cannot be undone!
    """
    try:
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        
        movie_title = movie.title
        
        # Delete all files from storage
        delete_tasks = []
        if movie.video_url:
            delete_tasks.append(storage_service.delete_file(movie.video_url, 'r2'))
        if movie.trailer_url:
            delete_tasks.append(storage_service.delete_file(movie.trailer_url, 'r2'))
        if movie.poster_url:
            delete_tasks.append(storage_service.delete_file(movie.poster_url, 'firebase'))
        if movie.banner_url:
            delete_tasks.append(storage_service.delete_file(movie.banner_url, 'firebase'))
        
        # Execute all deletes
        for task in delete_tasks:
            await task
        
        # Delete from database
        db.delete(movie)
        db.commit()
        
        logger.info(f"✅ Movie permanently deleted: {movie_title}")
        return {"data": {"message": f"Movie '{movie_title}' permanently deleted"}}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error hard deleting movie {movie_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to permanently delete movie")