"""Subscription, LPS pricing, and Apple IAP receipt verification endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from mtm_gateway.config import get_settings
from mtm_gateway.middleware.identity import extract_wallet_from_x402
from mtm_gateway.middleware.tier import get_tier_info
from mtm_gateway.models import (
    LpsPricing,
    SubscriptionStatus,
    VerifyReceiptRequest,
    VerifyReceiptResponse,
)
from mtm_gateway.services.apple_iap import verify_jws_transaction
from mtm_gateway.services.laconic_registry import query_records, write_record
from mtm_gateway.services.lps_transfer import transfer_lps_to_user
from mtm_gateway.services.solana_rpc import invalidate_cache

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/subscriptions/status")
async def subscription_status(request: Request) -> SubscriptionStatus:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    tier_info = get_tier_info(wallet, settings)

    return SubscriptionStatus(
        tier=tier_info.tier,
        lifetimeSpend=tier_info.lifetime_spend,
        nextTierAt=tier_info.next_tier_at,
        nextTier=tier_info.next_tier,
        signalsPerDay=tier_info.signals_per_day,
        kolChannels=tier_info.wizard_follows,
        refreshesPerDay=tier_info.refreshes_per_day,
        autoExecute=tier_info.auto_execute,
    )


@router.post("/subscriptions/verify-receipt")
async def verify_receipt(request: Request, body: VerifyReceiptRequest) -> VerifyReceiptResponse:
    """Validate Apple IAP receipt, transfer LPS to user's wallet.

    Flow:
    1. Verify JWS signature traces to Apple's root CA
    2. Extract originalTransactionId and productId
    3. Check laconicd registry for duplicate (prevent double-minting)
    4. Transfer LPS from gateway wallet to user wallet
    5. Record transaction ID in laconicd to prevent replay
    6. Invalidate tier cache so next request reflects new spend
    7. Return LPS amount and tx signature

    The frontend calls this from iap.ts:56 after Apple confirms the purchase.
    """
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    # 1. Verify JWS and extract purchase info
    try:
        purchase = verify_jws_transaction(body.receipt)
    except ValueError as e:
        logger.warning("IAP receipt verification failed for wallet=%s: %s", wallet, e)
        raise HTTPException(status_code=400, detail=f"Receipt verification failed: {e}")

    # Verify productId matches what the frontend sent
    if purchase.product_id != body.productId:
        raise HTTPException(
            status_code=400,
            detail=f"Product ID mismatch: receipt has {purchase.product_id}, "
            f"request has {body.productId}",
        )

    # 2. Check for duplicate transaction (prevent double-minting)
    existing = await query_records(
        settings=settings,
        record_type="IAPTransaction",
        attributes={"originalTransactionId": purchase.original_transaction_id},
    )
    if existing:
        # Already processed — return the stored result without re-minting
        record = existing[0]
        logger.info(
            "Duplicate IAP transaction %s for wallet=%s — returning cached result",
            purchase.original_transaction_id,
            wallet,
        )
        return VerifyReceiptResponse(
            success=True,
            lpsAmount=float(record.get("lpsAmount", purchase.lps_amount)),
            lpsTxSignature=record.get("lpsTxSignature", ""),
            lifetimeSpend=float(record.get("lifetimeSpend", 0)),
            tier=record.get("tier", "free"),
        )

    # 3. Transfer LPS from gateway wallet to user's wallet
    try:
        tx_signature = transfer_lps_to_user(
            settings=settings,
            recipient_wallet=wallet,
            amount=purchase.lps_amount,
        )
    except ValueError as e:
        # Insufficient balance — operational issue, not user's fault
        logger.error("LPS transfer failed (insufficient balance): %s", e)
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unable to process purchase. Please try again later.",
        )
    except Exception:
        logger.exception("LPS transfer failed for wallet=%s", wallet)
        raise HTTPException(
            status_code=500,
            detail="Failed to transfer LPS tokens. Please contact support.",
        )

    # 4. Invalidate tier cache so the next request reflects the new LPS
    invalidate_cache(wallet)

    # 5. Get updated tier info
    tier_info = get_tier_info(wallet, settings)

    # 6. Record transaction in laconicd to prevent replay
    try:
        await write_record(
            settings=settings,
            record_type="IAPTransaction",
            attributes={
                "originalTransactionId": purchase.original_transaction_id,
                "wallet": wallet,
            },
            encrypted_data={
                "productId": purchase.product_id,
                "lpsAmount": str(purchase.lps_amount),
                "lpsTxSignature": tx_signature,
                "lifetimeSpend": str(tier_info.lifetime_spend),
                "tier": tier_info.tier,
                "environment": purchase.environment,
            },
        )
    except Exception:
        # The LPS transfer already happened but we couldn't record it.
        # Return error so the client retries — the dedup check at the top
        # will catch it if the record eventually lands, and if not, we
        # avoid silently succeeding without replay protection.
        logger.exception(
            "Failed to record IAP transaction %s — LPS transferred but not recorded",
            purchase.original_transaction_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Purchase processed but could not be recorded. "
            "Please retry — you will not be double-charged.",
        )

    logger.info(
        "IAP verified: wallet=%s product=%s lps=%s tx=%s tier=%s",
        wallet,
        purchase.product_id,
        purchase.lps_amount,
        tx_signature,
        tier_info.tier,
    )

    return VerifyReceiptResponse(
        success=True,
        lpsAmount=float(purchase.lps_amount),
        lpsTxSignature=tx_signature,
        lifetimeSpend=tier_info.lifetime_spend,
        tier=tier_info.tier,
    )


@router.get("/lps/pricing")
async def lps_pricing(request: Request) -> LpsPricing:
    settings = get_settings()
    return LpsPricing(
        signalRefresh=float(settings.refresh_price),
        signalExecution=float(settings.receipt_price),
        wizardSignalSend=float(settings.wizard_signal_price),
        laconicWallet=settings.solana_wallet_address,
    )
