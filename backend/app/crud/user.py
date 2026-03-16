from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from typing import Optional

from ..models.users import User
from ..auth import schemas as auth_schemas
from ..auth.utils import get_password_hash

async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """
    通过ID获取用户
    """
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()

async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """
    通过用户名获取用户
    """
    result = await db.execute(select(User).filter(User.username == username))
    return result.scalars().first()

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """
    通过邮箱获取用户
    """
    result = await db.execute(select(User).filter(User.email == email))
    return result.scalars().first()

async def create_user_email(db: AsyncSession, user_in: auth_schemas.UserCreateEmail) -> User:
    """
    通过邮箱和密码创建新用户
    """
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        email=user_in.email,
        hashed_password=hashed_password,
        username=user_in.username  # Use the provided username
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def delete_user_by_email(db: AsyncSession, email: str) -> bool:
    """
    通过邮箱删除用户（用于测试环境清理）
    """
    user = await get_user_by_email(db, email)
    if not user:
        return False
    await db.delete(user)
    await db.commit()
    return True
