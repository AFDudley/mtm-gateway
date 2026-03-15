"""laconicd registry client for encrypted record storage.

# Architecture: read and write paths are separate
#
# laconicd is a Cosmos SDK chain. Its GQL endpoint (LACONICD_GQL) is a
# read-side indexer that watches committed blocks and projects on-chain
# state into a queryable API. It does NOT support mutations.
#
# Writes go through the consensus layer: the gateway POSTs to a
# registry-writer sidecar (REGISTRY_WRITER_URL) which uses the
# @cerc-io/registry-sdk to sign and broadcast MsgSetRecord transactions
# to laconicd's Tendermint RPC. The sidecar owns the cosmos signing key,
# bond, and gas config. The gateway just sends JSON and gets back a
# record ID.
#
# Read path:  gateway → GQL indexer (http://laconicd:9473/api)
# Write path: gateway → registry-writer sidecar → Tendermint RPC
#
# The writer gets a receipt from the validator immediately on broadcast
# (tx hash + record ID in MsgSetRecordResponse), so the gateway knows
# the write succeeded without polling. Other readers querying GQL won't
# see the record until the indexer catches up to that block (~6s).
#
# GQL query notes:
#   - Variables use ValueInput wrappers: {key: k, value: {string: v}}
#   - Must pass all:true to include unnamed records (no authority name)
#   - The value field is a union type; use aliases to avoid conflicts:
#     ... on StringValue { string: value }
#     ... on IntValue { int: value }
#
# Encryption is application-layer. laconicd has no built-in encryption.
# Sensitive fields are AES-encrypted (Fernet) before storage. The
# ENCRYPTION_KEY is symmetric, generated at deploy time.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from mtm_gateway.config import Settings

logger = logging.getLogger(__name__)


def _get_cipher(encryption_key: str) -> Fernet:
    """Derive a Fernet key from the hex encryption key."""
    # Use PBKDF2 to derive a proper Fernet key from the hex key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mtm-gateway-registry",
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(bytes.fromhex(encryption_key)))
    return Fernet(key)


def _encrypt(data: dict, encryption_key: str) -> str:
    """Encrypt a dict to a base64 string."""
    cipher = _get_cipher(encryption_key)
    plaintext = json.dumps(data).encode()
    return cipher.encrypt(plaintext).decode()


def _decrypt(ciphertext: str, encryption_key: str) -> dict:
    """Decrypt a base64 string back to a dict."""
    cipher = _get_cipher(encryption_key)
    plaintext = cipher.decrypt(ciphertext.encode())
    return json.loads(plaintext)


async def write_record(
    settings: Settings,
    record_type: str,
    attributes: dict[str, str],
    encrypted_data: dict | None = None,
) -> str:
    """Write a record to laconicd via the registry-writer sidecar.

    Attributes are stored in plaintext (queryable).
    encrypted_data is AES-encrypted before storage.

    Returns the record ID.
    """
    if not settings.registry_writer_url:
        raise HTTPException(status_code=503, detail="REGISTRY_WRITER_URL not configured")

    if encrypted_data and not settings.encryption_key:
        raise HTTPException(status_code=503, detail="ENCRYPTION_KEY not configured")

    record: dict[str, str] = {"type": record_type, **attributes}

    if encrypted_data and settings.encryption_key:
        record["encryptedPayload"] = _encrypt(encrypted_data, settings.encryption_key)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{settings.registry_writer_url}/records",
                json={"record": record},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Failed to write to registry: %s", e)
            raise HTTPException(status_code=502, detail="Registry service unavailable") from e

        result = resp.json()
        record_id = result.get("id", "")
        logger.info("Wrote record type=%s id=%s", record_type, record_id)
        return record_id


async def query_records(
    settings: Settings,
    record_type: str,
    attributes: dict[str, str],
) -> list[dict[str, Any]]:
    """Query records from laconicd registry by type and attributes.

    Decrypts encrypted payloads and merges into the returned dicts.
    """
    if not settings.laconicd_gql:
        raise HTTPException(status_code=503, detail="LACONICD_GQL not configured")

    # Build attribute filter
    attr_filter = {**attributes, "type": record_type}

    query = """
    query QueryRecords($attributes: [KeyValueInput!]) {
        queryRecords(attributes: $attributes, all: true) {
            id
            attributes {
                key
                value {
                    ... on StringValue { string: value }
                    ... on IntValue { int: value }
                    ... on FloatValue { float: value }
                    ... on BooleanValue { boolean: value }
                }
            }
        }
    }
    """

    kv_list = [{"key": k, "value": {"string": v}} for k, v in attr_filter.items()]
    variables = {"attributes": kv_list}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                settings.laconicd_gql,
                json={"query": query, "variables": variables},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Failed to query registry: %s", e)
            return []

        result = resp.json()

        if "errors" in result:
            logger.error("GraphQL errors querying records: %s", result["errors"])
            return []

    records = result.get("data", {}).get("queryRecords", [])
    decoded = []

    for record in records:
        entry: dict[str, Any] = {"id": record["id"]}

        # Flatten attributes — value is a union type with aliases:
        # StringValue→string, IntValue→int, FloatValue→float, BooleanValue→boolean
        for attr in record.get("attributes", []):
            val = attr["value"]
            if isinstance(val, dict):
                # Extract whichever alias is non-null
                entry[attr["key"]] = (
                    val.get("string")
                    if val.get("string") is not None
                    else val.get("int")
                    if val.get("int") is not None
                    else val.get("float")
                    if val.get("float") is not None
                    else val.get("boolean")
                )
            else:
                entry[attr["key"]] = val

        # Decrypt payload if present (stored as a regular attribute)
        payload = entry.pop("encryptedPayload", None)
        if payload and settings.encryption_key:
            try:
                decrypted = _decrypt(payload, settings.encryption_key)
                entry.update(decrypted)
            except Exception:
                logger.warning("Failed to decrypt record %s", record["id"])

        decoded.append(entry)

    return decoded


async def delete_records(
    settings: Settings,
    record_ids: list[str],
) -> None:
    """Delete records from laconicd via the registry-writer sidecar."""
    if not settings.registry_writer_url:
        raise HTTPException(status_code=503, detail="REGISTRY_WRITER_URL not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for record_id in record_ids:
            try:
                resp = await client.delete(
                    f"{settings.registry_writer_url}/records/{record_id}",
                )
                resp.raise_for_status()
                logger.info("Deleted record %s", record_id)
            except httpx.HTTPError as e:
                logger.error("Failed to delete record %s: %s", record_id, e)
