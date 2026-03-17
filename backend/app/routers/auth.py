from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import schemas as auth_schemas
from ..auth.utils import create_access_token, verify_password
from ..crud import user as crud_user
from ..db_utils import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register-email", response_model=auth_schemas.EmailLoginResponse)
async def register_email(user_in: auth_schemas.UserCreateEmail, db: AsyncSession = Depends(get_db)):
    db_user = await crud_user.get_user_by_email(db, email=user_in.email)
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    created_user = await crud_user.create_user_email(db=db, user_in=user_in)
    access_token = create_access_token(data={"sub": created_user.email})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "needs_interest_setup": False,
        "user_info": {"email": created_user.email, "username": created_user.username}
    }


@router.post("/login-email", response_model=auth_schemas.EmailLoginResponse)
async def login_email(user_in: auth_schemas.UserLoginEmail, db: AsyncSession = Depends(get_db)):
    user = await crud_user.get_user_by_email(db, email=user_in.email)
    if not user or not user.hashed_password or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "needs_interest_setup": False,
        "user_info": {"email": user.email, "username": user.username}
    }


@router.delete("/users/{email:path}")
async def delete_user(email: str, db: AsyncSession = Depends(get_db), x_test_mode: str = Header(None)):
    if x_test_mode != "true":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required or test mode not enabled")
    deleted = await crud_user.delete_user_by_email(db, email)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with email {email} not found")
    return {"message": f"User {email} deleted successfully", "email": email}
