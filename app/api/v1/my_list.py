from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from datetime import datetime
import logging

from ...database import get_db
from ...models.user import User, MyList
from ...api.deps import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


class MyListItemResponse(BaseModel):
    id: int
    user_id: int
    movie_id: int | None
    series_id: int | None
    created_at: str
    
    # Content details
    content_title: str | None = None
    content_poster: str | None = None
    content_type: str | None = None
    content_rating: float | None = None


@router.get("/", response_model=List[MyListItemResponse])
def get_my_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get user's My List (saved/favorite content)
    """
    try:
        my_list_items = db.query(MyList).filter(
            MyList.user_id == current_user.id
        ).order_by(desc(MyList.created_at)).all()
        
        result = []
        for item in my_list_items:
            content_title = None
            content_poster = None
            content_type = None
            content_rating = None
            
            if item.movie_id and item.movie:
                content_title = item.movie.title
                content_poster = item.movie.poster_url
                content_type = "movie"
                content_rating = item.movie.rating
            elif item.series_id and item.series:
                content_title = item.series.title
                content_poster = item.series.poster_url
                content_type = "series"
                content_rating = item.series.rating
            
            result.append(MyListItemResponse(
                id=item.id,
                user_id=item.user_id,
                movie_id=item.movie_id,
                series_id=item.series_id,
                created_at=item.created_at.isoformat(),
                content_title=content_title,
                content_poster=content_poster,
                content_type=content_type,
                content_rating=content_rating,
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching my list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch my list"
        )


@router.post("/movie/{movie_id}")
def add_movie_to_list(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Add a movie to user's My List
    """
    try:
        # Check if already in list
        existing = db.query(MyList).filter(
            MyList.user_id == current_user.id,
            MyList.movie_id == movie_id
        ).first()
        
        if existing:
            return {
                "message": "Movie already in your list",
                "in_my_list": True
            }
        
        # Add to list
        my_list_item = MyList(
            user_id=current_user.id,
            movie_id=movie_id,
            created_at=datetime.utcnow()
        )
        db.add(my_list_item)
        db.commit()
        
        logger.info(f"✅ Movie {movie_id} added to My List for user {current_user.id}")
        
        return {
            "message": "Added to My List",
            "in_my_list": True
        }
        
    except Exception as e:
        logger.error(f"Error adding movie to list: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add to my list"
        )


@router.delete("/movie/{movie_id}")
def remove_movie_from_list(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Remove a movie from user's My List
    """
    try:
        my_list_item = db.query(MyList).filter(
            MyList.user_id == current_user.id,
            MyList.movie_id == movie_id
        ).first()
        
        if my_list_item:
            db.delete(my_list_item)
            db.commit()
            logger.info(f"🗑️ Movie {movie_id} removed from My List for user {current_user.id}")
            return {"message": "Removed from My List", "in_my_list": False}
        
        return {"message": "Movie not in your list", "in_my_list": False}
        
    except Exception as e:
        logger.error(f"Error removing movie from list: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove from my list"
        )


@router.get("/movie/{movie_id}/check")
def check_movie_in_list(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Check if a movie is in user's My List
    """
    try:
        exists = db.query(MyList).filter(
            MyList.user_id == current_user.id,
            MyList.movie_id == movie_id
        ).first() is not None
        
        return {"in_my_list": exists}
        
    except Exception as e:
        logger.error(f"Error checking my list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check my list"
        )


# Similar endpoints for series
@router.post("/series/{series_id}")
def add_series_to_list(
    series_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a series to user's My List"""
    try:
        existing = db.query(MyList).filter(
            MyList.user_id == current_user.id,
            MyList.series_id == series_id
        ).first()
        
        if existing:
            return {"message": "Series already in your list", "in_my_list": True}
        
        my_list_item = MyList(
            user_id=current_user.id,
            series_id=series_id,
            created_at=datetime.utcnow()
        )
        db.add(my_list_item)
        db.commit()
        
        return {"message": "Added to My List", "in_my_list": True}
        
    except Exception as e:
        logger.error(f"Error adding series to list: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add to my list"
        )


@router.delete("/series/{series_id}")
def remove_series_from_list(
    series_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a series from user's My List"""
    try:
        my_list_item = db.query(MyList).filter(
            MyList.user_id == current_user.id,
            MyList.series_id == series_id
        ).first()
        
        if my_list_item:
            db.delete(my_list_item)
            db.commit()
            return {"message": "Removed from My List", "in_my_list": False}
        
        return {"message": "Series not in your list", "in_my_list": False}
        
    except Exception as e:
        logger.error(f"Error removing series from list: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove from my list"
        )


@router.get("/series/{series_id}/check")
def check_series_in_list(
    series_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if a series is in user's My List"""
    try:
        exists = db.query(MyList).filter(
            MyList.user_id == current_user.id,
            MyList.series_id == series_id
        ).first() is not None
        
        return {"in_my_list": exists}
        
    except Exception as e:
        logger.error(f"Error checking my list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check my list"
        )