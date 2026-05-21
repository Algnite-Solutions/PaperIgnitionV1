import hmac
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from ..db_utils import get_db
from ..models.users import User

# JWT configuration — MUST be set via JWT_SECRET_KEY env var or security.jwt_secret_key in config
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days

# 密码哈希工具 - bcrypt for new hashes, argon2 for verifying legacy hashes
from pwdlib.hashers.bcrypt import BcryptHasher

_hashers = [BcryptHasher()]
try:
    from pwdlib.hashers.argon2 import Argon2Hasher
    _hashers.append(Argon2Hasher())
except ImportError:
    pass
pwd_hash = PasswordHash(tuple(_hashers))

def verify_password(plain_password, hashed_password):
    """验证密码"""
    return pwd_hash.verify(plain_password, hashed_password)

def get_password_hash(password):
    """获取密码哈希"""
    return pwd_hash.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """创建访问令牌"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Security scheme for token
reusable_oauth2 = HTTPBearer() # Using HTTPBearer

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(reusable_oauth2),
    db: AsyncSession = Depends(get_db)
):
    """获取当前认证用户"""
    # TODO: Add proper scope checking if using scopes

    try:
        # Decode JWT token
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        # The 'sub' claim should contain the user identifier (openid or username)
        user_identifier: str = payload.get("sub")
        if user_identifier is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证凭证",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # TODO: Handle potential token expiration if not handled by jwt.decode

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Find user in database by identifier (assuming 'sub' is either email or wx_openid)
    # In a real app, you might need to store token payload info to distinguish
    result = await db.execute(
        select(User).where(
            or_(
                User.email == user_identifier,
                User.wx_openid == user_identifier
            )
        ).options(selectinload(User.research_domains))
    )
    user = result.scalars().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # TODO: Add logic to check if user is active or has necessary permissions/scopes
    # if not user.is_active:
    #     raise HTTPException(status_code=400, detail="Inactive user")

    return user


async def verify_service_token(
    x_service_token: str = Header(..., alias="X-Service-Token"),
):
    """Verify that the request comes from a trusted service (orchestrator)."""
    expected = os.environ.get("SERVICE_TOKEN", "")
    if not expected or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )
    return True
