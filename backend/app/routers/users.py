import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..auth.schemas import UserOut, UserProfileUpdate
from ..auth.utils import get_current_user
from ..db_utils import get_db, get_index_service_url
from ..models.users import FavoritePaper, ResearchDomain, User, UserPaperRecommendation
from ..utils.index_utils import get_openai_client, translate_text

logger = logging.getLogger(__name__)


class UserInterestUpdate(BaseModel):
    research_domain_ids: List[int]


class ResearchDomainOut(BaseModel):
    id: int
    name: str


class RewriteInterestUpdate(BaseModel):
    username: str
    rewrite_interest: str


router = APIRouter(prefix="/users", tags=["users"])


def save_recommendations(username, papers, backend_api_url):
    """Save recommended papers to database"""
    import requests
    for paper in papers:
        data = {
            "paper_id": paper.get("doc_id"),
            "title": paper.get("title", ""),
            "authors": paper.get("authors", ""),
            "abstract": paper.get("abstract", ""),
            "url": paper.get("url", ""),
            "content": paper.get("content", ""),
            "blog": paper.get("blog", ""),
            "recommendation_reason": paper.get("recommendation_reason", ""),
            "relevance_score": paper.get("score", 0.0)
        }
        try:
            resp = requests.post(
                f"{backend_api_url}/api/papers/recommend",
                params={"username": username},
                json=data,
                timeout=30.0
            )
            if resp.status_code == 201:
                logger.info(f"Recommendation saved: {paper.get('doc_id')}")
            else:
                logger.error(f"Recommendation save failed: {paper.get('doc_id')}, reason: {resp.text}")
        except Exception as e:
            logger.error(f"Recommendation save error: {paper.get('doc_id')}, error: {e}")


@router.get("/me", response_model=UserOut)
async def get_current_user_info(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get current user info (JWT authenticated)"""
    research_domain_ids = []
    if current_user.research_domains:
        for domain in current_user.research_domains:
            research_domain_ids.append(domain.id)

    favorite_count = await db.scalar(
        select(func.count(FavoritePaper.id)).where(FavoritePaper.user_id == current_user.id)
    )

    viewed_count = await db.scalar(
        select(func.count(UserPaperRecommendation.id)).where(
            UserPaperRecommendation.username == current_user.username,
            UserPaperRecommendation.viewed.is_(True)
        )
    )

    days_active = 0
    if current_user.created_at:
        now = datetime.now(timezone.utc)
        days_active = (now - current_user.created_at).days

    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "is_active": current_user.is_active,
        "research_interests_text": current_user.research_interests_text,
        "research_domain_ids": research_domain_ids,
        "activity_data": {
            "favorite_count": favorite_count or 0,
            "viewed_count": viewed_count or 0,
            "days_active": days_active
        }
    }


@router.post("/interests", response_model=UserOut)
async def update_interests(
    interests: UserInterestUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user research interests"""
    user = current_user

    result = await db.execute(
        select(ResearchDomain).where(ResearchDomain.id.in_(interests.research_domain_ids))
    )
    domains = result.scalars().all()

    if len(domains) != len(interests.research_domain_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more research domain IDs are invalid"
        )

    user.research_domains = domains

    await db.commit()
    await db.refresh(user)

    updated_domain_ids = [domain.id for domain in user.research_domains]

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "research_interests_text": user.research_interests_text,
        "research_domain_ids": updated_domain_ids
    }


@router.get("/research_domains", response_model=List[ResearchDomainOut])
async def get_research_domains(db: AsyncSession = Depends(get_db)):
    """Get all research domains"""
    result = await db.execute(select(ResearchDomain))
    research_domains = result.scalars().all()
    return research_domains


async def translate_and_update_in_background(user_id: int, text_to_translate: str):
    """Background task: translate text and update database"""
    try:
        logger.info(f"Starting background translation for user_id={user_id}")

        from ..db_utils import get_database_manager, load_config
        config = load_config()
        openai_config = config.get("OPENAI_SERVICE", {})
        client = get_openai_client(
            base_url=openai_config.get("base_url", "https://api.deepseek.com"),
            api_key=openai_config.get("api_key", "EMPTY")
        )

        english_text = translate_text(client, text_to_translate)

        if not english_text:
            logger.warning(f"Translation result empty for user_id: {user_id}")
            return

        db_manager = get_database_manager()
        async with db_manager.get_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()

            if user:
                user.rewrite_interest = english_text
                await session.commit()
            else:
                logger.error(f"Background task: user with id {user_id} not found")

    except Exception as e:
        logger.exception(f"Background translation task failed: {e}")


@router.put("/me/profile", response_model=UserOut)
async def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    index_service_url: str = Depends(get_index_service_url)
):
    """Update current user profile"""
    research_interests_changed = False
    new_research_interests_text = None

    if profile_data.research_interests_text is not None and profile_data.research_interests_text != current_user.research_interests_text:
        research_interests_changed = True
        new_research_interests_text = profile_data.research_interests_text
        current_user.research_interests_text = profile_data.research_interests_text

    if profile_data.email is not None:
        current_user.email = profile_data.email
    if profile_data.push_frequency is not None:
        current_user.push_frequency = profile_data.push_frequency

    if profile_data.research_domain_ids is not None:
        result = await db.execute(select(ResearchDomain).where(ResearchDomain.id.in_(profile_data.research_domain_ids)))
        research_domains = result.scalars().all()
        if len(research_domains) != len(profile_data.research_domain_ids):
            raise HTTPException(status_code=400, detail="One or more research domain IDs are invalid")
        current_user.research_domains = research_domains

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    if research_interests_changed and new_research_interests_text:
        try:
            asyncio.create_task(
                translate_and_update_in_background(
                    current_user.id,
                    new_research_interests_text
                )
            )
            logger.info(f"Created background translation task for user {current_user.username}")
        except Exception as e:
            logger.exception(f"Failed to create background translation task: {e}")

    return current_user


@router.get("/all", response_model=List[UserOut])
async def get_all_users_info(db: AsyncSession = Depends(get_db)):
    """Get all users info"""
    result = await db.execute(select(User))
    users = result.scalars().all()

    response_users = []
    for user in users:
        research_domain_ids = []
        response_users.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "research_interests_text": user.research_interests_text,
            "profile_json": user.profile_json,
            "research_domain_ids": research_domain_ids
        })
    return response_users


@router.get("/by_email/{username}", response_model=UserOut)
async def get_user_by_email(
    username: str,
    db: AsyncSession = Depends(get_db)
):
    """Get user details by username"""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with username {username} not found"
        )

    research_domain_ids = []

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "research_interests_text": user.research_interests_text,
        "profile_json": user.profile_json,
        "research_domain_ids": research_domain_ids
    }


@router.get("/rewrite_interest/empty", response_model=List[dict])
async def get_users_with_empty_rewrite_interest(db: AsyncSession = Depends(get_db)):
    """Get all users with empty rewrite_interest but non-empty research_interests_text"""
    result = await db.execute(
        select(User).where(
            and_(
                User.rewrite_interest.is_(None),
                User.research_interests_text.is_not(None),
                User.research_interests_text != ""
            )
        )
    )
    users = result.scalars().all()
    response = []
    for user in users:
        response.append({
            "username": user.username,
            "research_interests_text": user.research_interests_text
        })
    return response


@router.post("/rewrite_interest/batch_update")
async def batch_update_rewrite_interest(
    db: AsyncSession = Depends(get_db)
):
    """Batch translate research_interests_text and store in rewrite_interest field"""
    try:
        result = await db.execute(select(User))
        users = result.scalars().all()

        from ..db_utils import load_config
        config = load_config()
        openai_config = config.get("OPENAI_SERVICE", {})
        client = get_openai_client(
            base_url=openai_config.get("base_url", "https://api.deepseek.com"),
            api_key=openai_config.get("api_key", "EMPTY")
        )

        updated = []
        failed = []

        for user in users:
            try:
                if user.research_interests_text and len(user.research_interests_text.strip()) > 0:
                    interests_text = user.research_interests_text
                    logger.info(f"Translating for user {user.username}: '{interests_text[:50]}...'")

                    english_text = translate_text(client, interests_text)

                    if english_text:
                        user.rewrite_interest = english_text
                        updated.append({
                            "username": user.username,
                            "original": interests_text,
                            "translated": english_text
                        })
                        logger.info(f"Successfully translated for user {user.username}")
                    else:
                        failed.append({
                            "username": user.username,
                            "error": "Translation result empty"
                        })
                else:
                    logger.info(f"User {user.username} has no research_interests_text, skipping")

            except Exception as e:
                failed.append({
                    "username": user.username,
                    "error": str(e)
                })
                logger.error(f"Error translating for user {user.username}: {e}")

        await db.commit()

        return {
            "message": "Batch translation complete",
            "total_users": len(users),
            "updated": updated,
            "failed": failed,
            "success_count": len(updated),
            "failed_count": len(failed)
        }

    except Exception as e:
        logger.error(f"Batch translation task failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch translation failed: {str(e)}"
        )
