"""API-key authentication and rate limiting."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request
from slowapi import Limiter

from .config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    expected = get_settings().api_key
    # constant-time comparison, so response timing reveals nothing about the key
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail={"code": "unauthorised",
                                                      "message": "Missing or invalid API key"})
    return x_api_key


def _rate_key(request: Request) -> str:
    return request.headers.get("X-API-Key") or (request.client.host if request.client else "anon")


limiter = Limiter(key_func=_rate_key, storage_uri=None)
