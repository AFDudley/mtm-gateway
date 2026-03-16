"""x402 paying client for k_solana_backtest.

Uses the x402 SDK's httpx client to automatically handle the
402 → pay → retry flow when fetching signal data.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from solders.keypair import Keypair
from x402 import x402Client
from x402.http.clients.httpx import x402HttpxClient
from x402.mechanisms.svm.exact import ExactSvmScheme
from x402.mechanisms.svm.signers import KeypairSigner

from mtm_gateway.config import Settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0


@asynccontextmanager
async def _get_client(settings: Settings) -> AsyncGenerator[x402HttpxClient, None]:
    """Create an x402-enabled httpx client for backtest requests."""
    keypair = Keypair.from_base58_string(settings.solana_wallet_private_key)
    signer = KeypairSigner(keypair)
    scheme = ExactSvmScheme(signer=signer, rpc_url=settings.solana_rpc)

    client = x402Client()
    client.register(settings.solana_network, scheme)

    async with x402HttpxClient(
        client, base_url=settings.backtest_upstream, timeout=REQUEST_TIMEOUT
    ) as http:
        yield http


async def _x402_fetch(settings: Settings, method: str, path: str) -> Any:
    """Make an x402-authenticated request to the backtest service."""
    async with _get_client(settings) as client:
        if method == "GET":
            resp = await client.get(path)
        else:
            resp = await client.post(path)

        if resp.status_code == 503:
            return {"signals": [], "count": 0}

        resp.raise_for_status()
        return resp.json()


async def _x402_fetch_binary(settings: Settings, path: str) -> bytes:
    """Same as _x402_fetch but returns binary response (for PNG charts)."""
    async with _get_client(settings) as client:
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.content


# --- Public API ---


async def fetch_buy_signals(settings: Settings) -> dict:
    return await _x402_fetch(settings, "GET", "/api/signals/buys")


async def fetch_short_signals(settings: Settings) -> dict:
    return await _x402_fetch(settings, "GET", "/api/signals/shorts")


async def fetch_performance(settings: Settings, token: str) -> dict:
    return await _x402_fetch(settings, "GET", f"/api/performance/{token}")


async def fetch_equity_chart(settings: Settings, token: str) -> bytes:
    return await _x402_fetch_binary(settings, f"/api/charts/equity/{token}")


async def fetch_correlation_chart(settings: Settings, lookback: int) -> bytes:
    return await _x402_fetch_binary(settings, f"/api/charts/correlation/{lookback}")


async def fetch_pairs(settings: Settings) -> dict:
    return await _x402_fetch(settings, "GET", "/api/pairs")


async def trigger_rerun(settings: Settings) -> dict:
    return await _x402_fetch(settings, "POST", "/api/trigger-rerun")


async def fetch_status(settings: Settings) -> dict:
    """Status endpoint is free — no x402 payment needed."""
    async with _get_client(settings) as client:
        resp = await client.get("/api/status")
        resp.raise_for_status()
        return resp.json()
