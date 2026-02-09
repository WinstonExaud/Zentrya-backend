# app/api/v1/categories.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import Category
from typing import Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/categories", tags=["categories"])


# Pydantic models
class CategoryCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/list", status_code=status.HTTP_200_OK)
def list_categories(
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Get all categories with optional filtering"""
    try:
        logger.info(f"list_categories called with skip={skip}, limit={limit}, is_active={is_active}")
        
        query = db.query(Category)
        
        # Apply filter if is_active is specified
        if is_active is not None:
            query = query.filter(Category.is_active == is_active)
        else:
            # By default, show only active categories
            query = query.filter(Category.is_active == True)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        categories = query.offset(skip).limit(limit).all()
        
        logger.info(f"Found {len(categories)} categories")
        return {
            "total": total,
            "categories": [
                {
                    "id": cat.id,
                    "name": cat.name,
                    "slug": cat.slug,
                    "description": cat.description,
                    "is_active": cat.is_active,
                }
                for cat in categories
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch categories: {str(e)}")


@router.get("/slug/{slug}")
def get_category_by_slug(slug: str, db: Session = Depends(get_db)):
    """Get single category by slug"""
    try:
        category = db.query(Category).filter(Category.slug == slug).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        return {
            "data": {
                "id": category.id,
                "name": category.name,
                "slug": category.slug,
                "description": category.description,
                "is_active": category.is_active,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching category by slug {slug}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch category")


@router.get("/{category_id}")
def get_category(category_id: int, db: Session = Depends(get_db)):
    """Get single category by ID"""
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        return {
            "data": {
                "id": category.id,
                "name": category.name,
                "slug": category.slug,
                "description": category.description,
                "is_active": category.is_active,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching category {category_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch category")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(category_data: CategoryCreate, db: Session = Depends(get_db)):
    """Create new category"""
    try:
        # Check if slug already exists
        existing = db.query(Category).filter(Category.slug == category_data.slug).first()
        if existing:
            raise HTTPException(status_code=400, detail="Category slug already exists")
        
        # Check if name already exists
        existing_name = db.query(Category).filter(Category.name == category_data.name).first()
        if existing_name:
            raise HTTPException(status_code=400, detail="Category name already exists")
        
        category = Category(
            name=category_data.name,
            slug=category_data.slug,
            description=category_data.description,
            is_active=True
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        
        logger.info(f"Category created: {category.name}")
        return {
            "data": {
                "id": category.id,
                "name": category.name,
                "message": "Category created successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating category: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create category: {str(e)}")


@router.put("/{category_id}")
def update_category(
    category_id: int,
    category_data: CategoryUpdate,
    db: Session = Depends(get_db)
):
    """Update category"""
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Update fields if provided
        if category_data.name is not None:
            # Check if new name already exists (excluding current category)
            existing = db.query(Category).filter(
                Category.name == category_data.name,
                Category.id != category_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Category name already exists")
            category.name = category_data.name
        
        if category_data.slug is not None:
            # Check if new slug already exists (excluding current category)
            existing = db.query(Category).filter(
                Category.slug == category_data.slug,
                Category.id != category_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Category slug already exists")
            category.slug = category_data.slug
        
        if category_data.description is not None:
            category.description = category_data.description
        
        if category_data.is_active is not None:
            category.is_active = category_data.is_active
        
        db.commit()
        db.refresh(category)
        
        logger.info(f"Category updated: {category.name}")
        return {
            "data": {
                "id": category.id,
                "name": category.name,
                "message": "Category updated successfully"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating category {category_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update category")


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Delete category (soft delete via is_active)"""
    try:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Soft delete
        category.is_active = False
        db.commit()
        
        logger.info(f"Category deleted: {category.name}")
        return {"data": {"message": "Category deleted successfully"}}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting category {category_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete category")