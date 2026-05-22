import os

from fastapi import Request
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address


def _user_key(request: Request) -> str:
    """Rate-limit key: decode JWT sub claim if present, else client IP.

    Reads the token directly from the Authorization header — does NOT depend
    on request.state.user (which slowapi's decorator-phase check runs before
    FastAPI resolves Depends(get_current_user)).
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth[7:],
                os.environ.get("JWT_SECRET_KEY", ""),
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except JWTError:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_user_key)
