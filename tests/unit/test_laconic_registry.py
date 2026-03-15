"""Tests for laconic_registry service — configuration validation.

Device registration returns 502 when LACONICD_GQL or ENCRYPTION_KEY
are not configured. The registry client must fail fast with a clear
error rather than sending requests to empty URLs or silently dropping
encrypted data.
"""

import pytest
from fastapi import HTTPException

from mtm_gateway.config import Settings


class TestWriteRecordValidation:
    """write_record must reject invalid configuration at call time."""

    @pytest.mark.asyncio
    async def test_write_record_raises_when_laconicd_gql_empty(self) -> None:
        """Posting to an empty URL causes 502. Catch this early with 503."""
        from mtm_gateway.services.laconic_registry import write_record

        settings = Settings(laconicd_gql="", encryption_key="aa" * 16)

        with pytest.raises(HTTPException) as exc_info:
            await write_record(
                settings=settings,
                record_type="DeviceRegistration",
                attributes={"wallet": "test-wallet"},
                encrypted_data={"fcmToken": "token-123"},
            )
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_write_record_raises_when_encryption_key_empty(self) -> None:
        """Encrypted data without a key is data loss. Must raise, not skip."""
        from mtm_gateway.services.laconic_registry import write_record

        settings = Settings(
            laconicd_gql="http://localhost:9473/api",
            encryption_key="",
        )

        with pytest.raises(HTTPException) as exc_info:
            await write_record(
                settings=settings,
                record_type="DeviceRegistration",
                attributes={"wallet": "test-wallet"},
                encrypted_data={"fcmToken": "token-123"},
            )
        assert exc_info.value.status_code == 503


class TestQueryRecordsValidation:
    """query_records must reject invalid configuration."""

    @pytest.mark.asyncio
    async def test_query_records_raises_when_laconicd_gql_empty(self) -> None:
        """Querying with no URL configured is a server misconfiguration."""
        from mtm_gateway.services.laconic_registry import query_records

        settings = Settings(laconicd_gql="", encryption_key="aa" * 16)

        with pytest.raises(HTTPException) as exc_info:
            await query_records(
                settings=settings,
                record_type="DeviceRegistration",
                attributes={"wallet": "test-wallet"},
            )
        assert exc_info.value.status_code == 503
