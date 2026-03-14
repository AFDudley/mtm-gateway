"""E2E test fixtures for mtm-gateway.

Provides HTTP clients configured from environment variables,
targeting a running gateway instance.
"""

import os

import httpx
import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def gateway_url() -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8091")


@pytest.fixture(scope="session")
def solana_rpc() -> str:
    return os.environ.get("SOLANA_RPC", "http://localhost:8899")


@pytest.fixture(scope="session")
def laconicd_gql() -> str:
    return os.environ.get("LACONICD_GQL", "http://localhost:9473/api")


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


@pytest_asyncio.fixture
async def laconicd_client(laconicd_gql: str) -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=laconicd_gql, timeout=10.0) as c:
        yield c
