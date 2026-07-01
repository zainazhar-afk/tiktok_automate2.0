"""Billing, usage quota, and rights-attestation gates."""
from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import httpx
from fastapi import HTTPException, Request, status

from app.auth import AuthUser
from app.config import get_settings
from app.services import state_store

FEATURE_LABELS = {
    "download": "downloads",
    "process": "processed videos",
    "transcription": "transcriptions",
    "variant": "variant generations",
    "timeline_render": "timeline renders",
}


@dataclass(frozen=True)
class UsageLimit:
    event_type: str
    limit: int


def _period_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _limits() -> dict[str, UsageLimit]:
    settings = get_settings()
    return {
        "download": UsageLimit("download", settings.monthly_download_limit),
        "process": UsageLimit("process", settings.monthly_process_limit),
        "transcription": UsageLimit("transcription", settings.monthly_transcription_limit),
        "variant": UsageLimit("variant", settings.monthly_variant_limit),
        "timeline_render": UsageLimit("timeline_render", settings.monthly_timeline_render_limit),
    }


def _current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def _bypass_user(user: AuthUser) -> bool:
    return user.role in {"developer", "service"} or user.user_id in {"local-dev", "service-api-key"}


def _profile(user: AuthUser) -> dict:
    settings = get_settings()
    stored = state_store.get_account_profile(user.user_id) or {}
    jwt_plan = user.plan.strip()
    jwt_status = user.subscription_status.strip().lower()
    jwt_customer = user.stripe_customer_id.strip()

    if jwt_plan or jwt_status or jwt_customer:
        stored = state_store.save_account_profile(
            user.user_id,
            plan=jwt_plan or stored.get("plan") or settings.default_plan,
            subscription_status=jwt_status or stored.get("subscription_status") or "inactive",
            stripe_customer_id=jwt_customer or stored.get("stripe_customer_id"),
            rights_accepted=stored.get("rights_accepted"),
            metadata=stored.get("metadata", {}),
        )

    if not stored:
        status_value = "active" if (not settings.billing_required or _bypass_user(user)) else "inactive"
        stored = state_store.save_account_profile(
            user.user_id,
            plan=jwt_plan or settings.default_plan,
            subscription_status=jwt_status or status_value,
            stripe_customer_id=jwt_customer or None,
            rights_accepted=_bypass_user(user) and not settings.require_rights_attestation,
            metadata={},
        )
    return stored


def _active_subscription(profile: dict) -> bool:
    settings = get_settings()
    status_value = str(profile.get("subscription_status") or "").lower()
    return status_value in settings.allowed_subscription_statuses


def usage_status(user: AuthUser) -> dict:
    settings = get_settings()
    profile = _profile(user)
    period_start = _period_start()
    totals = state_store.usage_totals(user.user_id, period_start)
    usage = {}
    for feature, limit in _limits().items():
        used = int(totals.get(limit.event_type, 0))
        usage[feature] = {
            "label": FEATURE_LABELS.get(feature, feature),
            "used": used,
            "limit": limit.limit,
            "remaining": max(0, limit.limit - used) if limit.limit >= 0 else None,
        }
    subscription_active = (not settings.billing_required) or _active_subscription(profile) or _bypass_user(user)
    rights_accepted = (not settings.require_rights_attestation) or bool(profile.get("rights_accepted")) or _bypass_user(user)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "plan": profile.get("plan") or settings.default_plan,
        "subscription_status": profile.get("subscription_status") or "inactive",
        "subscription_active": subscription_active,
        "billing_required": settings.billing_required,
        "rights_required": settings.require_rights_attestation,
        "rights_accepted": rights_accepted,
        "period_start": period_start,
        "usage": usage,
        "stripe_configured": bool(settings.stripe_secret_key and settings.stripe_price_id),
        "stripe_customer_id": profile.get("stripe_customer_id") or user.stripe_customer_id or "",
    }


def require_feature(
    request: Request,
    feature: str,
    *,
    quantity: int = 1,
    rights_required: bool = False,
    metadata: dict | None = None,
) -> dict:
    settings = get_settings()
    user = _current_user(request)
    profile = _profile(user)
    quantity = max(1, int(quantity or 1))

    if settings.require_rights_attestation and rights_required and not (profile.get("rights_accepted") or _bypass_user(user)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Confirm that you own or have rights to use this source media before continuing.",
        )

    if settings.billing_required and not (_active_subscription(profile) or _bypass_user(user)):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required for this action.",
        )

    limit = _limits().get(feature)
    if limit and limit.limit >= 0 and not _bypass_user(user):
        totals = state_store.usage_totals(user.user_id, _period_start())
        used = int(totals.get(limit.event_type, 0))
        if used + quantity > limit.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Monthly {FEATURE_LABELS.get(feature, feature)} limit reached.",
            )
        state_store.record_usage(user.user_id, limit.event_type, quantity, metadata)

    return usage_status(user)


def set_rights_attestation(user: AuthUser, accepted: bool) -> dict:
    profile = _profile(user)
    state_store.save_account_profile(
        user.user_id,
        plan=profile.get("plan"),
        subscription_status=profile.get("subscription_status"),
        stripe_customer_id=profile.get("stripe_customer_id"),
        rights_accepted=accepted,
        metadata=profile.get("metadata", {}),
    )
    return usage_status(user)


async def create_checkout_session(user: AuthUser) -> dict:
    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="Stripe checkout is not configured")
    app_url = settings.app_url.rstrip("/")
    profile = _profile(user)
    data = {
        "mode": "subscription",
        "line_items[0][price]": settings.stripe_price_id,
        "line_items[0][quantity]": "1",
        "success_url": f"{app_url}/account?billing=success",
        "cancel_url": f"{app_url}/account?billing=cancelled",
        "client_reference_id": user.user_id,
        "metadata[user_id]": user.user_id,
        "subscription_data[metadata][user_id]": user.user_id,
        "customer_email": user.email,
    }
    if profile.get("stripe_customer_id"):
        data.pop("customer_email", None)
        data["customer"] = profile["stripe_customer_id"]
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=data,
            auth=(settings.stripe_secret_key, ""),
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Stripe checkout failed: {resp.text[:300]}")
    payload = resp.json()
    return {"id": payload.get("id"), "url": payload.get("url")}


async def create_portal_session(user: AuthUser) -> dict:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe customer portal is not configured")
    profile = _profile(user)
    customer = profile.get("stripe_customer_id") or user.stripe_customer_id
    if not customer:
        raise HTTPException(status_code=400, detail="No Stripe customer is linked to this account")
    return_url = settings.stripe_portal_return_url or f"{settings.app_url.rstrip('/')}/account"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.stripe.com/v1/billing_portal/sessions",
            data={"customer": customer, "return_url": return_url},
            auth=(settings.stripe_secret_key, ""),
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Stripe portal failed: {resp.text[:300]}")
    payload = resp.json()
    return {"id": payload.get("id"), "url": payload.get("url")}


def verify_stripe_webhook(payload: bytes, signature_header: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured")
    pieces: dict[str, list[str]] = {}
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        pieces.setdefault(key, []).append(value)
    timestamp = pieces.get("t", [""])[0]
    signatures = pieces.get("v1", [])
    if not timestamp or not signatures:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature header")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook timestamp") from exc
    if abs(time.time() - timestamp_value) > 300:
        raise HTTPException(status_code=400, detail="Expired Stripe webhook signature")
    expected = hmac.new(
        settings.stripe_webhook_secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + payload,
        sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, item) for item in signatures):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")
    return json.loads(payload.decode("utf-8"))


def handle_stripe_event(event: dict[str, Any]) -> dict:
    event_type = str(event.get("type") or "")
    obj = event.get("data", {}).get("object", {})
    if event_type == "checkout.session.completed":
        user_id = obj.get("metadata", {}).get("user_id") or obj.get("client_reference_id")
        if user_id:
            state_store.save_account_profile(
                str(user_id),
                subscription_status="active",
                stripe_customer_id=str(obj.get("customer") or ""),
                metadata={"checkout_session": obj.get("id"), "subscription": obj.get("subscription")},
            )
            return {"handled": True, "user_id": user_id}
    if event_type.startswith("customer.subscription."):
        user_id = obj.get("metadata", {}).get("user_id")
        customer = str(obj.get("customer") or "")
        if not user_id and customer:
            existing = state_store.get_account_profile_by_customer(customer)
            user_id = existing.get("owner_id") if existing else None
        if user_id:
            state_store.save_account_profile(
                str(user_id),
                subscription_status=str(obj.get("status") or "inactive"),
                stripe_customer_id=customer,
                metadata={"subscription": obj.get("id"), "stripe_event": event_type},
            )
            return {"handled": True, "user_id": user_id}
    return {"handled": False}
