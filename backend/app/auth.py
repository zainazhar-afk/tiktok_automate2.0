"""Request authentication helpers for production deployments."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient

from app.config import get_settings

_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str = ""
    role: str = "authenticated"


def _public_paths() -> tuple[str, ...]:
    return (
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
    )


def is_public_request(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    path = request.url.path
    return path in _public_paths() or path.startswith("/_next/")


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return request.query_params.get("access_token", "").strip()


def _service_key_allowed(request: Request) -> bool:
    settings = get_settings()
    if not settings.service_api_key:
        return False
    return request.headers.get("x-api-key") == settings.service_api_key


def _jwks() -> PyJWKClient:
    global _jwks_client
    settings = get_settings()
    if not settings.supabase_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase JWKS URL is not configured",
        )
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.supabase_jwks_url)
    return _jwks_client


def _issuer() -> str | None:
    url = get_settings().supabase_url.rstrip("/")
    return f"{url}/auth/v1" if url else None


def verify_token(token: str) -> AuthUser:
    try:
        signing_key = _jwks().get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=_issuer(),
            options={"verify_aud": False},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired session: {exc}",
        ) from exc

    exp = float(claims.get("exp", 0) or 0)
    if exp and exp < time.time():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    aud = claims.get("aud")
    if aud and aud not in {"authenticated", "service_role"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported token audience")

    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session subject")

    return AuthUser(
        user_id=user_id,
        email=str(claims.get("email") or claims.get("user_metadata", {}).get("email") or ""),
        role=str(claims.get("role") or "authenticated"),
    )


async def authenticate_request(request: Request) -> AuthUser | None:
    settings = get_settings()
    if not settings.require_auth:
        return AuthUser(user_id="local-dev", email="local@dev", role="developer")
    if is_public_request(request):
        return None
    if _service_key_allowed(request):
        return AuthUser(user_id="service-api-key", role="service")

    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return verify_token(token)
