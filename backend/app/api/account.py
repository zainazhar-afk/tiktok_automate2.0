"""Account, entitlement, rights, and billing endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.services import entitlements

router = APIRouter()


def _user(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.get("/status")
async def account_status(request: Request):
    return entitlements.usage_status(_user(request))


@router.post("/rights")
async def update_rights_attestation(request: Request, payload: dict):
    accepted = bool(payload.get("accepted"))
    return entitlements.set_rights_attestation(_user(request), accepted)


@router.post("/billing/checkout")
async def create_checkout(request: Request):
    return await entitlements.create_checkout_session(_user(request))


@router.post("/billing/portal")
async def create_portal(request: Request):
    return await entitlements.create_portal_session(_user(request))


@router.post("/billing/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    event = entitlements.verify_stripe_webhook(payload, signature)
    return entitlements.handle_stripe_event(event)
