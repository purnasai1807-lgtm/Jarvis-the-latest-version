"""
Mobile API authentication — single static API key from config.

Phone clients send `Authorization: Bearer <key>` on every request to mobile
endpoints. Configured under `apis.mobile.api_key` in config.yaml.

If the key is missing or set to the placeholder, the dependency rejects every
request — fail closed, never expose the brain unauthenticated.
"""

import secrets

from fastapi import Header, HTTPException, status
from loguru import logger


_PLACEHOLDER = "YOUR_MOBILE_API_KEY"
_warned_no_key = False


def _get_configured_key() -> str:
    from ui.dashboard import _config
    return (
        _config.get("apis", {})
        .get("mobile", {})
        .get("api_key", "")
        .strip()
    )


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: enforce Bearer token matches config."""
    global _warned_no_key

    expected = _get_configured_key()
    if not expected or expected == _PLACEHOLDER:
        if not _warned_no_key:
            logger.warning(
                "Mobile API key not configured (apis.mobile.api_key). "
                "All /api/mobile requests will be rejected. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
            _warned_no_key = True
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mobile API key not configured on server.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = authorization[len("Bearer "):].strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
