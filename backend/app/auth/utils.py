import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
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
from ..models.api_keys import UserApiKey
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
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
):
    """Verify that the request comes from a trusted service (orchestrator)."""
    expected = os.environ.get("SERVICE_TOKEN", "")
    if not x_service_token or not expected or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )
    return True


def _service_token_matches(x_service_token: Optional[str]) -> bool:
    expected = os.environ.get("SERVICE_TOKEN", "")
    return bool(x_service_token and expected and hmac.compare_digest(x_service_token, expected))


# ── API Key helpers ──────────────────────────────────────────────────────────

API_KEY_PREFIX = "pi_live_"


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    raw = secrets.token_urlsafe(24)
    full_key = f"{API_KEY_PREFIX}{raw}"
    return full_key, _hash_api_key(full_key)


def validate_api_key_format(key: str) -> bool:
    return key.startswith(API_KEY_PREFIX) and len(key) > len(API_KEY_PREFIX)


async def _user_from_api_key(
    api_key: Optional[str],
    db: AsyncSession,
) -> Optional[User]:
    if not api_key or not validate_api_key_format(api_key):
        return None
    key_hash = _hash_api_key(api_key)
    result = await db.execute(
        select(UserApiKey)
        .where(UserApiKey.key_hash == key_hash, UserApiKey.revoked_at.is_(None))
        .options(selectinload(UserApiKey.user).selectinload(User.research_domains))
    )
    api_key_obj = result.scalars().first()
    if api_key_obj is None:
        return None
    now = datetime.now(timezone.utc)
    if api_key_obj.last_used_at is None or (now - api_key_obj.last_used_at).total_seconds() > 60:
        api_key_obj.last_used_at = now
        await db.flush()
    return api_key_obj.user


async def _user_from_jwt(
    credentials: Optional[HTTPAuthorizationCredentials],
    db: AsyncSession,
) -> Optional[User]:
    if credentials is None:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            return None
    except JWTError:
        return None
    result = await db.execute(
        select(User).where(or_(User.email == sub, User.wx_openid == sub))
    )
    return result.scalars().first()


_optional_bearer = HTTPBearer(auto_error=False)


async def verify_owner_or_service(
    username: str,
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Allow if X-Service-Token is valid OR JWT/API-key user matches `username`."""
    if _service_token_matches(x_service_token):
        return True
    user = await _user_from_api_key(x_api_key, db)
    if user is not None and user.username == username:
        return True
    user = await _user_from_jwt(credentials, db)
    if user is not None and user.username == username:
        return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authorized")


async def verify_jwt_or_service(
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Allow if X-Service-Token is valid OR valid X-API-Key OR any valid JWT."""
    if _service_token_matches(x_service_token):
        return True
    user = await _user_from_api_key(x_api_key, db)
    if user is not None:
        return True
    user = await _user_from_jwt(credentials, db)
    if user is not None:
        return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
