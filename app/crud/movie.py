from typing import List, Optional
from sqlalchemy.orm import Session
from ..crud.base import CRUDBase
from ..models.movie import Movie
from ..schemas.movie import MovieCreate, MovieUpdate

class CRUDMovie(CRUDBase[Movie, MovieCreate, MovieUpdate]):
    def get_by_slug(self, db: Session, *, slug: str) -> Optional[Movie]:
        return db.query(Movie).filter(Movie.slug == slug).first()

    def get_by_category(
        self, db: Session, *, category_id: int, skip: int = 0, limit: int = 100
    ) -> List[Movie]:
        return (
            db.query(Movie)
            .filter(Movie.category_id == category_id)
            .filter(Movie.is_active == True)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_featured(self, db: Session, *, limit: int = 10) -> List[Movie]:
        return (
            db.query(Movie)
            .filter(Movie.is_featured == True)
            .filter(Movie.is_active == True)
            .order_by(Movie.created_at.desc())
            .limit(limit)
            .all()
        )

    def search(
        self, db: Session, *, query: str, skip: int = 0, limit: int = 100
    ) -> List[Movie]:
        return (
            db.query(Movie)
            .filter(Movie.title.ilike(f"%{query}%"))
            .filter(Movie.is_active == True)
            .offset(skip)
            .limit(limit)
            .all()
        )

movie = CRUDMovie(Movie)