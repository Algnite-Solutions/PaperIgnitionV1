import hashlib
import os

from cachetools import TTLCache
from fastapi import Request
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

_api_key_cache: TTLCache = TTLCache(maxsize=1024, ttl=300)


def _user_key(request: Request) -> str:
    """Rate-limit key: API key > JWT sub > client IP."""
    api_key = request.headers.get("x-api-key", "")
    if api_key.startswith("pi_live_"):
        cache_key = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        cached = _api_key_cache.get(cache_key)
        if cached:
            return cached
        user_key = f"apikey:{cache_key}"
        _api_key_cache[cache_key] = user_key
        return user_key

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
