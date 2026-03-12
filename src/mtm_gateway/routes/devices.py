"""Device registration endpoints for FCM push notifications.

Stores encrypted wallet→FCM token mappings in laconicd registry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from mtm_gateway.config import get_settings
from mtm_gateway.middleware.identity import extract_wallet_from_x402
from mtm_gateway.models import DeviceRegisterRequest, DeviceUnregisterRequest
from mtm_gateway.services.laconic_registry import delete_records, query_records, write_record

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/devices/register")
async def register_device(request: Request, body: DeviceRegisterRequest) -> dict:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    # Check if this wallet+token combo already exists
    existing = await query_records(
        settings=settings,
        record_type="DeviceRegistration",
        attributes={"wallet": wallet},
    )

    for record in existing:
        if record.get("fcmToken") == body.fcmToken:
            return {"success": True}  # Already registered

    await write_record(
        settings=settings,
        record_type="DeviceRegistration",
        attributes={"wallet": wallet},
        encrypted_data={
            "fcmToken": body.fcmToken,
            "platform": body.platform,
            "appVersion": body.appVersion,
        },
    )

    logger.info("Device registered: wallet=%s platform=%s", wallet, body.platform)
    return {"success": True}


@router.delete("/devices/unregister")
async def unregister_device(request: Request, body: DeviceUnregisterRequest) -> dict:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    records = await query_records(
        settings=settings,
        record_type="DeviceRegistration",
        attributes={"wallet": wallet},
    )

    deleted = False
    for record in records:
        if record.get("fcmToken") == body.fcmToken:
            await delete_records(settings=settings, record_ids=[record["id"]])
            deleted = True
            break

    if not deleted:
        logger.warning("Device token not found for wallet=%s", wallet)

    return {"success": True}
