from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import schemas as auth_schemas
from ..auth.utils import create_access_token, get_current_user, get_password_hash, verify_password
from ..crud import user as crud_user
from ..db_utils import get_db
from ..models.users import User
from ..services.email import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_base_url(request: Request) -> str:
    """Return the frontend base URL from config (APP_SERVICE.host)."""
    try:
        app_service = request.app.state.config.get("APP_SERVICE", {})
        host = app_service.get("host", "")
        if host and not host.startswith("${"):
            return host.rstrip("/")
    except Exception:
        pass
    return str(request.base_url).rstrip("/")


@router.post("/register-email", response_model=auth_schemas.EmailLoginResponse)
async def register_email(
    user_in: auth_schemas.UserCreateEmail,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    db_user = await crud_user.get_user_by_email(db, email=user_in.email)
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    created_user = await crud_user.create_user_email(db=db, user_in=user_in)

    # Send verification email (background, non-blocking)
    token = crud_user.generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await crud_user.set_verification_token(db, created_user, token, expires_at)

    smtp_config = request.app.state.smtp_config
    base_url = _get_base_url(request)
    background_tasks.add_task(
        send_verification_email, smtp_config, created_user.email, created_user.username, token, base_url
    )

    access_token = create_access_token(data={"sub": created_user.email})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "needs_interest_setup": False,
        "user_info": {"email": created_user.email, "username": created_user.username},
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
        "user_info": {"email": user.email, "username": user.username},
    }


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    user = await crud_user.get_user_by_verification_token(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")
    if user.email_verification_expires_at and user.email_verification_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token has expired")
    await crud_user.verify_email(db, user)
    return {"message": "Email verified successfully"}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await crud_user.get_user_by_email(db, body.email)
    if user:
        token = crud_user.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await crud_user.set_reset_token(db, user, token, expires_at)

        smtp_config = request.app.state.smtp_config
        base_url = _get_base_url(request)
        background_tasks.add_task(
            send_password_reset_email, smtp_config, user.email, user.username, token, base_url
        )
    # Always return 200 to prevent email enumeration
    return {"message": "If that email exists, a reset link has been sent"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 6 characters")
    user = await crud_user.get_user_by_reset_token(db, body.token)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")
    await crud_user.reset_password(db, user, get_password_hash(body.new_password))
    return {"message": "Password updated successfully"}


@router.post("/resend-verification")
async def resend_verification(
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.is_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already verified")

    # Rate-limit: block if token was issued < 1 minute ago
    if current_user.email_verification_expires_at:
        issued_at_approx = current_user.email_verification_expires_at - timedelta(hours=24)
        if issued_at_approx > datetime.now(timezone.utc) - timedelta(minutes=1):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Please wait before resending")

    token = crud_user.generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await crud_user.set_verification_token(db, current_user, token, expires_at)

    smtp_config = request.app.state.smtp_config
    base_url = _get_base_url(request)
    background_tasks.add_task(
        send_verification_email, smtp_config, current_user.email, current_user.username, token, base_url
    )
    return {"message": "Verification email sent"}


@router.delete("/users/{email:path}")
async def delete_user(email: str, db: AsyncSession = Depends(get_db), x_test_mode: str = Header(None)):
    if x_test_mode != "true":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required or test mode not enabled")
    deleted = await crud_user.delete_user_by_email(db, email)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with email {email} not found")
    return {"message": f"User {email} deleted successfully", "email": email}
