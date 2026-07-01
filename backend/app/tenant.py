"""Request-scoped tenant ownership helpers."""
from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar, Token

from app.auth import AuthUser

_current_owner_id: ContextVar[str] = ContextVar("current_owner_id", default="local-dev")


def owner_from_user(user: AuthUser | None) -> str:
    if not user:
        return "anonymous"
    return user.user_id or "anonymous"


def set_current_owner(owner_id: str) -> Token[str]:
    return _current_owner_id.set(owner_id or "anonymous")


def reset_current_owner(token: Token[str]) -> None:
    _current_owner_id.reset(token)


def current_owner_id() -> str:
    return _current_owner_id.get()


def can_see_legacy(owner_id: str | None = None) -> bool:
    return (owner_id or current_owner_id()) in {"local-dev", "service-api-key"}


def owner_storage_prefix(owner_id: str | None = None) -> str:
    owner = owner_id or current_owner_id()
    if can_see_legacy(owner):
        return ""
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()[:12]


def storage_video_id(video_id: str, owner_id: str | None = None) -> str:
    """Stable owner-scoped file stem for shared local/R2 media names."""
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", video_id or "").strip("_")
    prefix = owner_storage_prefix(owner_id)
    return f"{prefix}_{stem}" if prefix else stem
