"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException, status

import config


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """Guard internal endpoints with a shared secret.

    The primary access control is Railway's private network (the service has no
    public domain). This token is defence in depth for anything that can reach
    the private network. If `API_INTERNAL_TOKEN` is unset, the check is skipped
    (useful for local dev); set it in production.
    """
    expected = config.API_INTERNAL_TOKEN
    if not expected:
        return
    if x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid internal token",
        )
