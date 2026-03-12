"""x402 paying client for k_solana_backtest.

The gateway pays USDC to the backtest service for signal data.
Flow: send request → receive 402 → parse payment requirements →
sign USDC SPL transfer with gateway's Solana keypair → retry with X-PAYMENT header.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from solana.rpc.api import Client as SolanaClient
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from mtm_gateway.config import Settings
from mtm_gateway.services.spl_instructions import (
    get_associated_token_address,
    transfer_checked,
)

logger = logging.getLogger(__name__)

# USDC on Solana mainnet
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

REQUEST_TIMEOUT = 30.0


async def _sign_usdc_transfer(
    settings: Settings,
    pay_to: str,
    amount_str: str,
) -> str:
    """Sign a USDC SPL transfer from the gateway's wallet.

    Returns base64-encoded serialized signed transaction.
    """
    keypair = Keypair.from_base58_string(settings.solana_wallet_private_key)
    mint = Pubkey.from_string(USDC_MINT)
    recipient = Pubkey.from_string(pay_to)

    source_ata = get_associated_token_address(keypair.pubkey(), mint)
    dest_ata = get_associated_token_address(recipient, mint)

    # USDC has 6 decimals
    amount = int(float(amount_str) * 1_000_000)

    ix = transfer_checked(
        source=source_ata,
        mint=mint,
        dest=dest_ata,
        owner=keypair.pubkey(),
        amount=amount,
        decimals=6,
    )

    client = SolanaClient(settings.solana_rpc)
    blockhash_resp = client.get_latest_blockhash()
    blockhash = blockhash_resp.value.blockhash

    msg = MessageV0.try_compile(
        payer=keypair.pubkey(),
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )
    tx = VersionedTransaction(msg, [keypair])

    return base64.b64encode(bytes(tx)).decode()


async def _x402_fetch(
    settings: Settings,
    method: str,
    path: str,
) -> Any:
    """Make an x402-authenticated request to the backtest service.

    Handles the 402 → pay → retry flow.
    """
    url = f"{settings.backtest_upstream}{path}"

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # First request — expect 402
        if method == "GET":
            resp = await client.get(url)
        else:
            resp = await client.post(url)

        if resp.status_code != 402:
            resp.raise_for_status()
            return resp.json()

        # Parse payment requirements from response body or header
        requirements = _parse_payment_requirements(resp)
        if not requirements:
            raise ValueError(f"402 response but no payment requirements from {url}")

        pay_to = requirements["pay_to"]
        price = requirements["price"]

        # Sign USDC payment
        signed_tx = await _sign_usdc_transfer(settings, pay_to, price)

        # Retry with payment proof
        payment_header = json.dumps({
            "scheme": "exact",
            "network": "solana",
            "payload": signed_tx,
        })

        if method == "GET":
            resp2 = await client.get(url, headers={"X-PAYMENT": payment_header})
        else:
            resp2 = await client.post(url, headers={"X-PAYMENT": payment_header})

        resp2.raise_for_status()
        return resp2.json()


async def _x402_fetch_binary(
    settings: Settings,
    path: str,
) -> bytes:
    """Same as _x402_fetch but returns binary response (for PNG charts)."""
    url = f"{settings.backtest_upstream}{path}"

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(url)

        if resp.status_code != 402:
            resp.raise_for_status()
            return resp.content

        requirements = _parse_payment_requirements(resp)
        if not requirements:
            raise ValueError(f"402 response but no payment requirements from {url}")

        signed_tx = await _sign_usdc_transfer(
            settings, requirements["pay_to"], requirements["price"]
        )
        payment_header = json.dumps({
            "scheme": "exact",
            "network": "solana",
            "payload": signed_tx,
        })

        resp2 = await client.get(url, headers={"X-PAYMENT": payment_header})
        resp2.raise_for_status()
        return resp2.content


def _parse_payment_requirements(resp: httpx.Response) -> dict[str, str] | None:
    """Parse x402 payment requirements from 402 response.

    Tries response body first, then X-Payment-Requirements header.
    Handles both x402 SDK format and flat format.
    """
    # Try body
    try:
        body = resp.json()
        pay_to = (
            body.get("accepts", {}).get("payTo")
            or body.get("pay_to")
            or body.get("payTo")
        )
        price = str(
            body.get("accepts", {}).get("maxAmountRequired")
            or body.get("price")
            or body.get("maxAmountRequired")
        )
        if pay_to and price:
            return {"pay_to": pay_to, "price": price}
    except Exception:
        pass

    # Try header
    header = resp.headers.get("X-Payment-Requirements")
    if header:
        try:
            req = json.loads(header)
            pay_to = req.get("payTo") or req.get("pay_to")
            price = str(req.get("maxAmountRequired") or req.get("price"))
            if pay_to and price:
                return {"pay_to": pay_to, "price": price}
        except Exception:
            pass

    return None


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
    url = f"{settings.backtest_upstream}/api/status"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
