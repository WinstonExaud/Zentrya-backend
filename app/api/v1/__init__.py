# app/api/v1/__init__.py
from fastapi import APIRouter
from .movies import router as movies_router
from .upload import router as upload_router
from .genres import router as genres_router
from .categories import router as categories_router
from .dashboard import router as dashboard_router

api_router = APIRouter()

api_router.include_router(movies_router)
api_router.include_router(upload_router)
api_router.include_router(genres_router)
api_router.include_router(categories_router)
api_router.include_router(dashboard_router)