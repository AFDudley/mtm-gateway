"""E2E test fixtures for mtm-gateway.

Provides HTTP clients configured from environment variables,
targeting a running gateway instance with x402 payment support.
"""

import os

import httpx
import pytest
import pytest_asyncio
from solders.keypair import Keypair
from x402 import x402Client
from x402.http.clients.httpx import x402HttpxClient
from x402.mechanisms.svm.exact import ExactSvmScheme
from x402.mechanisms.svm.signers import KeypairSigner


@pytest.fixture(scope="session")
def gateway_url() -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8091")


@pytest.fixture(scope="session")
def solana_rpc() -> str:
    return os.environ.get("SOLANA_RPC", "http://localhost:8899")


@pytest.fixture(scope="session")
def solana_network() -> str:
    return os.environ.get("SOLANA_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")


@pytest.fixture(scope="session")
def laconicd_gql() -> str:
    return os.environ.get("LACONICD_GQL", "http://localhost:9473/api")


@pytest.fixture(scope="session")
def test_wallet_key() -> str:
    key = os.environ.get("TEST_WALLET_KEY", "")
    assert key, "TEST_WALLET_KEY must be set to run E2E tests"
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
    """httpx client with automatic x402 payment handling.

    Creates a Solana keypair from TEST_WALLET_KEY, registers the ExactSvm
    scheme, and wraps httpx so 402 responses are retried with a valid
    payment header.
    """
    keypair = Keypair.from_base58_string(test_wallet_key)
    signer = KeypairSigner(keypair)
    scheme = ExactSvmScheme(signer=signer, rpc_url=solana_rpc)

    x402_client = x402Client()
    x402_client.register(solana_network, scheme)

    async with x402HttpxClient(
        x402_client, base_url=gateway_url, timeout=30.0
    ) as c:
        yield c
