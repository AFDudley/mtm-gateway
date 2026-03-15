"""E2E test fixtures for mtm-gateway.

Provides HTTP clients configured from environment variables,
targeting a running gateway instance with x402 payment support.

Two modes:
  1. External stack: set GATEWAY_URL + TEST_WALLET_KEY env vars
  2. VM: automatic — boots a QEMU VM with the full stack
"""

import logging
import os
from typing import Generator

import httpx
import pytest
import pytest_asyncio
from solders.keypair import Keypair
from x402 import x402Client
from x402.http.clients.httpx import x402HttpxClient
from x402.mechanisms.svm.exact import ExactSvmScheme
from x402.mechanisms.svm.signers import KeypairSigner

logger = logging.getLogger(__name__)

# Use external stack if GATEWAY_URL is set, otherwise boot a VM
_USE_VM = not os.environ.get("GATEWAY_URL")


@pytest.fixture(scope="session")
def _e2e_stack() -> Generator:
    """Boot a QEMU VM with the full stack if no external stack is configured."""
    if not _USE_VM:
        yield None
        return

    import signal

    from tests.e2e.vm_fixture import start_stack

    qemu_proc, info = start_stack()
    os.environ["GATEWAY_URL"] = info.gateway_url
    os.environ["SOLANA_RPC"] = info.solana_rpc
    os.environ["SOLANA_NETWORK"] = info.solana_network
    os.environ["LACONICD_GQL"] = info.laconicd_gql
    os.environ["TEST_WALLET_KEY"] = info.test_wallet_key
    yield info
    logger.info("Stopping QEMU VM...")
    qemu_proc.send_signal(signal.SIGTERM)
    qemu_proc.wait(timeout=10)


@pytest.fixture(scope="session")
def gateway_url(_e2e_stack: object) -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8091")


@pytest.fixture(scope="session")
def solana_rpc(_e2e_stack: object) -> str:
    return os.environ.get("SOLANA_RPC", "http://localhost:8899")


@pytest.fixture(scope="session")
def solana_network(_e2e_stack: object) -> str:
    return os.environ.get("SOLANA_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")


@pytest.fixture(scope="session")
def laconicd_gql(_e2e_stack: object) -> str:
    return os.environ.get("LACONICD_GQL", "http://localhost:9473/api")


@pytest.fixture(scope="session")
def test_wallet_key(_e2e_stack: object) -> str:
    key = os.environ.get("TEST_WALLET_KEY", "")
    assert key, "TEST_WALLET_KEY must be set (or use testcontainer mode)"
    return key


@pytest_asyncio.fixture
async def client(gateway_url: str) -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=gateway_url, timeout=30.0) as c:
        yield c


@pytest_asyncio.fixture
async def solana_client(solana_rpc: str) -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=solana_rpc, timeout=10.0) as c:
        yield c


@pytest_asyncio.fixture
async def laconicd_client(laconicd_gql: str) -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=laconicd_gql, timeout=10.0) as c:
        yield c


@pytest_asyncio.fixture
async def x402_pay(
    gateway_url: str,
    test_wallet_key: str,
    solana_rpc: str,
    solana_network: str,
) -> x402HttpxClient:
    """httpx client with automatic x402 payment handling."""
    keypair = Keypair.from_base58_string(test_wallet_key)
    signer = KeypairSigner(keypair)
    scheme = ExactSvmScheme(signer=signer, rpc_url=solana_rpc)

    x402_client = x402Client()
    x402_client.register(solana_network, scheme)

    async with x402HttpxClient(
        x402_client, base_url=gateway_url, timeout=30.0
    ) as c:
        yield c
