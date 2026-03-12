"""Signal endpoints.

Relays signals from k_solana_backtest, transforming from backtest format
to the SignalState shape the frontend store expects.

Transform logic matches backtestApi.ts:78-133:
- confidence = n_strategies / 19 (0.0-1.0)
- action: buys → "BUY", shorts → "SELL"
- asset: "$" + token
- reasoning: comma-joined strategy names
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from mtm_gateway.config import Settings, get_settings
from mtm_gateway.middleware.identity import extract_wallet_from_x402
from mtm_gateway.middleware.tier import (
    check_refresh_quota,
    check_signal_quota,
    record_refresh_use,
    record_signal_use,
)
from mtm_gateway.models import SignalReceiptRequest, SignalState, SignalsResponse
from mtm_gateway.services import backtest_client

logger = logging.getLogger(__name__)
router = APIRouter()

TOTAL_STRATEGIES = 19


def _transform_signals(raw_signals: list[dict], action: str) -> list[SignalState]:
    """Transform backtest SignalEntry list into SignalState list.

    Matches the transform in backtestApi.ts:78-133.
    """
    results = []
    for entry in raw_signals:
        n = entry.get("n_strategies", 0)
        strategies = entry.get("strategies_firing", [])
        token = entry.get("token", "UNKNOWN")

        results.append(SignalState(
            id=f"sig_{uuid.uuid4().hex[:12]}",
            asset=f"${token}",
            action=action,
            confidence=round(n / TOTAL_STRATEGIES, 2),
            entry=entry.get("spot_price", 0),
            reasoning=", ".join(strategies) if strategies else "Consensus signal",
            channelId="wizard_mtm",
        ))
    return results


@router.get("/signals/buys")
async def get_buy_signals(request: Request) -> SignalsResponse:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    allowed, remaining = check_signal_quota(wallet, settings)
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily signal limit reached. Upgrade tier.")

    data = await backtest_client.fetch_buy_signals(settings)
    signals = _transform_signals(data.get("signals", []), "BUY")

    record_signal_use(wallet)
    _, remaining = check_signal_quota(wallet, settings)

    return SignalsResponse(signals=signals, count=len(signals), remaining=remaining)


@router.get("/signals/shorts")
async def get_short_signals(request: Request) -> SignalsResponse:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    allowed, remaining = check_signal_quota(wallet, settings)
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily signal limit reached. Upgrade tier.")

    data = await backtest_client.fetch_short_signals(settings)
    signals = _transform_signals(data.get("signals", []), "SELL")

    record_signal_use(wallet)
    _, remaining = check_signal_quota(wallet, settings)

    return SignalsResponse(signals=signals, count=len(signals), remaining=remaining)


@router.post("/signals/refresh")
async def refresh_signals(request: Request) -> SignalsResponse:
    settings = get_settings()
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    allowed, remaining = check_refresh_quota(wallet, settings)
    if not allowed:
        raise HTTPException(status_code=429, detail="No refreshes remaining today. Upgrade tier.")

    # Trigger a rerun on the backtest service and fetch fresh results
    await backtest_client.trigger_rerun(settings)
    data = await backtest_client.fetch_buy_signals(settings)
    signals = _transform_signals(data.get("signals", []), "BUY")

    record_refresh_use(wallet)
    _, remaining = check_refresh_quota(wallet, settings)

    return SignalsResponse(signals=signals, count=len(signals), remaining=remaining)


@router.post("/signals/receipt")
async def signal_receipt(request: Request, body: SignalReceiptRequest) -> dict:
    """Record a signal action (APE/PASS).

    The x402 payment itself IS the receipt — on-chain, immutable, auditable.
    We just acknowledge it.
    """
    wallet = extract_wallet_from_x402(request)
    if not wallet:
        raise HTTPException(status_code=401, detail="No wallet identity in payment")

    logger.info(
        "Signal receipt: wallet=%s signal=%s action=%s asset=%s",
        wallet,
        body.signalId,
        body.action,
        body.asset,
    )

    return {"success": True}
