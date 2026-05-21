from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _user_key(request: Request) -> str:
    """Rate-limit key: authenticated user if available, else client IP."""
    user = getattr(request.state, "user", None)
    return getattr(user, "username", None) or get_remote_address(request)


limiter = Limiter(key_func=_user_key)
