"""
Sentinel-KE — Centralised rate limiter.

Import `limiter` and use `@limiter.limit("N/minute")` on route handlers.
Route handlers must accept `request: Request` as a parameter for slowapi to work.

Example:
    from app.core.rate_limit import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    async def login(request: Request, body: LoginBody):
        ...
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _build_limiter() -> Limiter:
    default_limit = f"{settings.rate_limit_global_per_min}/minute"
    return Limiter(
        key_func=get_remote_address,
        default_limits=[default_limit],
        enabled=settings.rate_limit_enabled,
    )


limiter = _build_limiter()
