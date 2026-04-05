from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..auth.utils import get_current_user
from ..db_utils import get_db
from ..models.users import FavoritePaper, User

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteRequest(BaseModel):
    paper_id: str
    title: str
    authors: str
    abstract: str
    url: str = ""


class FavoriteResponse(BaseModel):
    paper_id: str
    title: str
    authors: str
    abstract: str
    url: str = ""


@router.post("/add", status_code=status.HTTP_201_CREATED)
async def add_to_favorites(
    favorite_data: FavoriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add paper to favorites"""
    try:
        result = await db.execute(
            select(FavoritePaper).where(
                FavoritePaper.user_id == current_user.id,
                FavoritePaper.paper_id == favorite_data.paper_id
            )
        )
        existing_favorite = result.scalar_one_or_none()

        if existing_favorite:
            return {"message": "Paper already in favorites"}

        new_favorite = FavoritePaper(
            user_id=current_user.id,
            paper_id=favorite_data.paper_id,
            title=favorite_data.title,
            authors=favorite_data.authors,
            abstract=favorite_data.abstract,
            url=favorite_data.url
        )

        db.add(new_favorite)
        await db.commit()

        return {"message": "Paper added to favorites"}

    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add favorite")


@router.delete("/remove/{paper_id}")
async def remove_from_favorites(
    paper_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove paper from favorites"""
    try:
        result = await db.execute(
            select(FavoritePaper).where(
                FavoritePaper.user_id == current_user.id,
                FavoritePaper.paper_id == paper_id
            )
        )
        favorite = result.scalar_one_or_none()

        if not favorite:
            raise HTTPException(status_code=404, detail="Favorite not found")

        await db.delete(favorite)
        await db.commit()

        return {"message": "Paper removed from favorites"}

    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to remove favorite")


@router.get("/list", response_model=List[FavoriteResponse])
async def get_user_favorites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user favorites list"""
    try:
        result = await db.execute(
            select(FavoritePaper).where(
                FavoritePaper.user_id == current_user.id
            ).order_by(FavoritePaper.created_at.desc())
        )
        favorites = result.scalars().all()

        return [
            FavoriteResponse(
                paper_id=fav.paper_id,
                title=fav.title,
                authors=fav.authors,
                abstract=fav.abstract,
                url=fav.url or ""
            )
            for fav in favorites
        ]

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get favorites list")


@router.get("/check/{paper_id}")
async def check_if_favorited(
    paper_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check if a paper is favorited"""
    try:
        result = await db.execute(
            select(FavoritePaper).where(
                FavoritePaper.user_id == current_user.id,
                FavoritePaper.paper_id == paper_id
            )
        )
        favorite = result.scalar_one_or_none()

        return {"is_favorited": favorite is not None}

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to check favorite status")


class BatchCheckRequest(BaseModel):
    paper_ids: List[str]


class BatchCheckResponse(BaseModel):
    paper_id: str
    is_favorited: bool


@router.post("/batch-check", response_model=List[BatchCheckResponse])
async def batch_check_favorites(
    request: BatchCheckRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Batch check favorite status for multiple papers"""
    try:
        result = await db.execute(
            select(FavoritePaper.paper_id).where(
                FavoritePaper.user_id == current_user.id,
                FavoritePaper.paper_id.in_(request.paper_ids)
            )
        )
        favorited_ids = set(result.scalars().all())

        response = [
            BatchCheckResponse(
                paper_id=paper_id,
                is_favorited=paper_id in favorited_ids
            )
            for paper_id in request.paper_ids
        ]

        return response

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to batch check favorites")
