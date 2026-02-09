# app/api/v1/genres.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import Genre
from typing import Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/genres", tags=["genres"])


# Pydantic models
class GenreCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None


class GenreUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/list", status_code=status.HTTP_200_OK)
def list_genres(
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Get all genres with optional filtering"""
    try:
        logger.info(f"list_genres called with skip={skip}, limit={limit}, is_active={is_active}")
        
        query = db.query(Genre)
        
        # Apply filter if is_active is specified
        if is_active is not None:
            query = query.filter(Genre.is_active == is_active)
        else:
            # By default, show only active genres
            query = query.filter(Genre.is_active == True)
        
        # Get total count
        total = query.count()
        
        # Apply pagination and order by name
        genres = query.order_by(Genre.name).offset(skip).limit(limit).all()
        
        logger.info(f"Found {len(genres)} genres")
        return {
            "total": total,
            "genres": [
                {
                    "id": genre.id,
                    "name": genre.name,
                    "slug": genre.slug,
                    "description": genre.description,
                    "is_active": genre.is_active,
                }
                for genre in genres
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching genres: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch genres: {str(e)}")


@router.get("/slug/{slug}")
def get_genre_by_slug(slug: str, db: Session = Depends(get_db)):
    """Get single genre by slug"""
    try:
        genre = db.query(Genre).filter(Genre.slug == slug).first()
        if not genre:
            raise HTTPException(status_code=404, detail="Genre not found")
        
        return {
            "data": {
                "id": genre.id,
                "name": genre.name,
                "slug": genre.slug,
                "description": genre.description,
                "is_active": genre.is_active,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching genre by slug {slug}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch genre")


@router.get("/{genre_id}")
def get_genre(genre_id: int, db: Session = Depends(get_db)):
    """Get single genre by ID"""
    try:
        genre = db.query(Genre).filter(Genre.id == genre_id).first()
        if not genre:
            raise HTTPException(status_code=404, detail="Genre not found")
        
        return {
            "data": {
                "id": genre.id,
                "name": genre.name,
                "slug": genre.slug,
                "description": genre.description,
                "is_active": genre.is_active,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching genre {genre_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch genre")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_genre(genre_data: GenreCreate, db: Session = Depends(get_db)):
    """Create new genre"""
    try:
        # Check if slug already exists
        existing = db.query(Genre).filter(Genre.slug == genre_data.slug).first()
        if existing:
            raise HTTPException(status_code=400, detail="Genre slug already exists")
        
        # Check if name already exists
        existing_name = db.query(Genre).filter(Genre.name == genre_data.name).first()
        if existing_name:
            raise HTTPException(status_code=400, detail="Genre name already exists")
        
        genre = Genre(
            name=genre_data.name,
            slug=genre_data.slug,
            description=genre_data.description,
            is_active=True
        )
        db.add(genre)
        db.commit()
        db.refresh(genre)
        
        logger.info(f"Genre created: {genre.name}")
        return {
            "data": {
                "id": genre.id,
                "name": genre.name,
                "message": "Genre created successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating genre: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create genre: {str(e)}")


@router.put("/{genre_id}")
def update_genre(
    genre_id: int,
    genre_data: GenreUpdate,
    db: Session = Depends(get_db)
):
    """Update genre"""
    try:
        genre = db.query(Genre).filter(Genre.id == genre_id).first()
        if not genre:
            raise HTTPException(status_code=404, detail="Genre not found")
        
        # Update fields if provided
        if genre_data.name is not None:
            # Check if new name already exists (excluding current genre)
            existing = db.query(Genre).filter(
                Genre.name == genre_data.name,
                Genre.id != genre_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Genre name already exists")
            genre.name = genre_data.name
        
        if genre_data.slug is not None:
            # Check if new slug already exists (excluding current genre)
            existing = db.query(Genre).filter(
                Genre.slug == genre_data.slug,
                Genre.id != genre_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Genre slug already exists")
            genre.slug = genre_data.slug
        
        if genre_data.description is not None:
            genre.description = genre_data.description
        
        if genre_data.is_active is not None:
            genre.is_active = genre_data.is_active
        
        db.commit()
        db.refresh(genre)
        
        logger.info(f"Genre updated: {genre.name}")
        return {
            "data": {
                "id": genre.id,
                "name": genre.name,
                "message": "Genre updated successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating genre {genre_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update genre")


@router.delete("/{genre_id}")
def delete_genre(genre_id: int, db: Session = Depends(get_db)):
    """Delete genre (soft delete via is_active)"""
    try:
        genre = db.query(Genre).filter(Genre.id == genre_id).first()
        if not genre:
            raise HTTPException(status_code=404, detail="Genre not found")
        
        # Soft delete
        genre.is_active = False
        db.commit()
        
        logger.info(f"Genre deleted: {genre.name}")
        return {"data": {"message": "Genre deleted successfully"}}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting genre {genre_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete genre")