"""E2E test fixtures for mtm-gateway.

Provides HTTP clients and x402 payment helpers configured from environment
variables, targeting a running gateway instance.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Callable, Coroutine

import httpx
import pytest
import pytest_asyncio
from solana.rpc.api import Client as SolanaClient
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from mtm_gateway.services.spl_instructions import (
    get_associated_token_address,
    transfer_checked,
)


@pytest.fixture(scope="session")
def gateway_url() -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8091")


@pytest.fixture(scope="session")
def solana_rpc() -> str:
    return os.environ.get("SOLANA_RPC", "http://localhost:8899")


@pytest.fixture(scope="session")
def lps_mint_address() -> str:
    addr = os.environ.get("LPS_MINT_ADDRESS")
    if not addr:
        pytest.skip("LPS_MINT_ADDRESS not set")
    return addr


@pytest.fixture(scope="session")
def test_wallet_key() -> str:
    key = os.environ.get("TEST_WALLET_KEY")
    if not key:
        pytest.skip("TEST_WALLET_KEY not set")
    return key


@pytest_asyncio.fixture
async def client(gateway_url: str) -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=gateway_url, timeout=30.0) as c:
        yield c


# Type alias for the x402_pay callable.
X402PayFn = Callable[[str, str], Coroutine[None, None, httpx.Response]]


@pytest_asyncio.fixture
async def x402_pay(
    gateway_url: str,
    solana_rpc: str,
    lps_mint_address: str,
    test_wallet_key: str,
) -> X402PayFn:
    """Payment helper that executes the x402 402-pay-retry flow.

    Usage::

        resp = await x402_pay("/signals/buys", "GET")
        assert resp.status_code == 200
    """

    async def _pay(path: str, method: str = "GET") -> httpx.Response:
        keypair = Keypair.from_base58_string(test_wallet_key)
        mint = Pubkey.from_string(lps_mint_address)

        async with httpx.AsyncClient(base_url=gateway_url, timeout=30.0) as http:
            # 1. Initial request — expect 402 with payment requirements.
            if method.upper() == "GET":
                resp = await http.get(path)
            else:
                resp = await http.post(path)

            assert resp.status_code == 402, (
                f"Expected 402 from {path}, got {resp.status_code}"
            )

            # 2. Parse payment requirements from 402 body.
            body = resp.json()
            accepts = body.get("accepts", {})
            if isinstance(accepts, list):
                accepts = accepts[0]

            pay_to = accepts.get("payTo") or accepts.get("pay_to", "")
            price = str(
                accepts.get("maxAmountRequired") or accepts.get("price", "0")
            )
            assert pay_to, "402 response missing pay_to in accepts"

            recipient = Pubkey.from_string(pay_to)

            # 3. Sign M2M SPL token transfer.
            source_ata = get_associated_token_address(keypair.pubkey(), mint)
            dest_ata = get_associated_token_address(recipient, mint)

            # M2M token uses 6 decimals (matching USDC convention).
            decimals = 6
            amount = int(float(price) * 10**decimals)

            ix = transfer_checked(
                source=source_ata,
                mint=mint,
                dest=dest_ata,
                owner=keypair.pubkey(),
                amount=amount,
                decimals=decimals,
            )

            rpc_client = SolanaClient(solana_rpc)
            blockhash = rpc_client.get_latest_blockhash().value.blockhash

            msg = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=[ix],
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash,
            )
            tx = VersionedTransaction(msg, [keypair])

            # 4. Base64-encode the signed transaction.
            signed_tx_b64 = base64.b64encode(bytes(tx)).decode()

            # 5. Retry with X-PAYMENT header.
            payment_header = json.dumps({
                "scheme": "exact",
                "network": "solana",
                "payload": signed_tx_b64,
            })

            headers = {"X-PAYMENT": payment_header}
            if method.upper() == "GET":
                resp2 = await http.get(path, headers=headers)
            else:
                resp2 = await http.post(path, headers=headers)

            # 6. Return the response.
            return resp2

    return _pay
