"""Wizard (KOL provider) endpoints.

Wizard follows are encrypted laconicd registry records. Record existence
is public (follower count), but follower identity is encrypted — only
the gateway can decrypt for push targeting.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from mtm_gateway.config import get_settings
from mtm_gateway.middleware.identity import extract_wallet_from_x402
from mtm_gateway.middleware.tier import get_tier_info
from mtm_gateway.models import Wizard, WizardSignalRequest
from mtm_gateway.services.fcm import send_signal_to_tokens
from mtm_gateway.services.laconic_registry import (
    delete_records,
    query_records,
    write_record,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/wizards")
async def list_wizards(request: Request) -> dict:
    settings = get_settings()

    # Query wizard profile records from laconicd
    wizard_records = await query_records(
        settings=settings,
        record_type="WizardProfile",
        attributes={},
    )

    wizards = []
    for record in wizard_records:
        wizard_id = record.get("wizardId", "")

        # Count follower records for this wizard
        followers = await query_records(
            settings=settings,
            record_type="WizardFollow",
            attributes={"wizardId": wizard_id},
        )

        wizards.append(Wizard(
            id=wizard_id,
            name=record.get("name", ""),
            handle=record.get("handle", ""),
            avatarUrl=record.get("avatarUrl"),
            bio=record.get("bio"),
            winRate=record.get("winRate", 0),
            avgReturn=record.get("avgReturn", 0),
            signalsPerMonth=record.get("signalsPerMonth", 0),
            followers=len(followers),
            verified=record.get("verified", False),
            walletAddress=record.get("walletAddress", ""),
            createdAt=record.get("createdAt", ""),
        ))

    return {"wizards": [w.model_dump() for w in wizards]}


@router.post("/wizards/{wizard_id}/follow")
async def follow_wizard(wizard_id: str, request: Request) -> dict:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    tier_info = get_tier_info(wallet, settings)

    # Check tier allows wizard follows
    if tier_info.wizard_follows == 0:
        raise HTTPException(
            status_code=403,
            detail={"error": "tier_required", "requiredTier": "starter"},
        )

    # Check follow limit (skip for unlimited tiers)
    if tier_info.wizard_follows > 0:
        current_follows = await query_records(
            settings=settings,
            record_type="WizardFollow",
            attributes={"followerWallet": wallet},
        )
        # Don't count MTM default follows
        non_mtm = [f for f in current_follows if f.get("wizardId") != "wiz_mtm"]
        if len(non_mtm) >= tier_info.wizard_follows:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "tier_limit",
                    "currentCount": len(non_mtm),
                    "limit": tier_info.wizard_follows,
                    "requiredTier": "elite",
                },
            )

    # Check not already following
    existing = await query_records(
        settings=settings,
        record_type="WizardFollow",
        attributes={"wizardId": wizard_id, "followerWallet": wallet},
    )
    if existing:
        return {"success": True, "followedCount": len(existing), "limit": tier_info.wizard_follows}

    # Create encrypted follow record
    # The wallet attribute is stored encrypted, but wizardId is plaintext
    # so follower count can be derived publicly
    await write_record(
        settings=settings,
        record_type="WizardFollow",
        attributes={"wizardId": wizard_id, "followerWallet": wallet},
        encrypted_data={"wallet": wallet},
    )

    # Count updated follows
    all_follows = await query_records(
        settings=settings,
        record_type="WizardFollow",
        attributes={"followerWallet": wallet},
    )

    return {
        "success": True,
        "followedCount": len(all_follows),
        "limit": tier_info.wizard_follows,
    }


@router.delete("/wizards/{wizard_id}/follow")
async def unfollow_wizard(wizard_id: str, request: Request) -> dict:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    records = await query_records(
        settings=settings,
        record_type="WizardFollow",
        attributes={"wizardId": wizard_id, "followerWallet": wallet},
    )

    if records:
        await delete_records(settings=settings, record_ids=[r["id"] for r in records])

    remaining = await query_records(
        settings=settings,
        record_type="WizardFollow",
        attributes={"followerWallet": wallet},
    )

    return {"success": True, "followedCount": len(remaining)}


@router.post("/wizards/{wizard_id}/signal")
async def wizard_signal(wizard_id: str, request: Request, body: WizardSignalRequest) -> dict:
    """Wizard broadcasts a signal to all followers via FCM."""
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    # Verify this wallet owns the wizard profile
    wizard_records = await query_records(
        settings=settings,
        record_type="WizardProfile",
        attributes={"wizardId": wizard_id},
    )
    if not wizard_records or wizard_records[0].get("walletAddress") != wallet:
        raise HTTPException(status_code=403, detail="Not the owner of this wizard profile")

    # Get all follower records, decrypt to get wallets
    follower_records = await query_records(
        settings=settings,
        record_type="WizardFollow",
        attributes={"wizardId": wizard_id},
    )

    # Resolve FCM tokens for each follower
    signal_id = f"sig_wiz_{uuid.uuid4().hex[:12]}"
    fcm_tokens = []

    for follower in follower_records:
        follower_wallet = follower.get("wallet", "")
        if not follower_wallet:
            continue

        device_records = await query_records(
            settings=settings,
            record_type="DeviceRegistration",
            attributes={"wallet": follower_wallet},
        )
        for device in device_records:
            token = device.get("fcmToken")
            if token:
                fcm_tokens.append(token)

    # Send FCM data messages
    delivered = 0
    if fcm_tokens:
        signal_data = {
            "signalId": signal_id,
            "asset": body.asset,
            "action": body.action,
            "confidence": str(body.confidence),
            "reason": body.reasoning,
            "duration": body.duration,
            "wizardId": wizard_id,
        }
        delivered = await send_signal_to_tokens(settings, fcm_tokens, signal_data)

    return {"signalId": signal_id, "distributedTo": delivered}
