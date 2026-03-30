import secrets
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..auth import schemas as auth_schemas
from ..auth.utils import get_password_hash
from ..models.users import User


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()

async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).filter(User.username == username))
    return result.scalars().first()

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).filter(User.email == email))
    return result.scalars().first()

async def create_user_email(db: AsyncSession, user_in: auth_schemas.UserCreateEmail) -> User:
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        email=user_in.email,
        hashed_password=hashed_password,
        username=user_in.username
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def delete_user_by_email(db: AsyncSession, email: str) -> bool:
    user = await get_user_by_email(db, email)
    if not user:
        return False
    await db.delete(user)
    await db.commit()
    return True


# --- Email verification helpers ---

async def get_user_by_verification_token(db: AsyncSession, token: str) -> User | None:
    result = await db.execute(select(User).filter(User.email_verification_token == token))
    return result.scalars().first()

async def set_verification_token(db: AsyncSession, user: User, token: str, expires_at: datetime) -> None:
    user.email_verification_token = token
    user.email_verification_expires_at = expires_at
    await db.commit()
    await db.refresh(user)

async def verify_email(db: AsyncSession, user: User) -> None:
    user.is_verified = True
    user.email_verification_token = None
    user.email_verification_expires_at = None
    await db.commit()


# --- Password reset helpers ---

async def get_user_by_reset_token(db: AsyncSession, token: str) -> User | None:
    result = await db.execute(select(User).filter(User.password_reset_token == token))
    user = result.scalars().first()
    if not user:
        return None
    if user.password_reset_expires_at and user.password_reset_expires_at < datetime.now(timezone.utc):
        return None
    return user

async def set_reset_token(db: AsyncSession, user: User, token: str, expires_at: datetime) -> None:
    user.password_reset_token = token
    user.password_reset_expires_at = expires_at
    await db.commit()
    await db.refresh(user)

async def reset_password(db: AsyncSession, user: User, new_hashed_password: str) -> None:
    user.hashed_password = new_hashed_password
    user.password_reset_token = None
    user.password_reset_expires_at = None
    await db.commit()


def generate_token() -> str:
    return secrets.token_urlsafe(32)
