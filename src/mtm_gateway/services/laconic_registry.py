"""laconicd registry client for encrypted record storage.

Records are stored in laconicd's on-chain registry via GraphQL.
Sensitive fields are AES-encrypted application-side before writing.
The ENCRYPTION_KEY is symmetric, generated at deploy time.

Registry has no built-in encryption — all privacy is at the application layer.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx
from cryptography.fernet import Fernet
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
    """Write a record to laconicd registry.

    Attributes are stored in plaintext (queryable).
    encrypted_data is AES-encrypted before storage.

    Returns the record ID.
    """
    record = {
        "type": record_type,
        "attributes": attributes,
    }

    if encrypted_data and settings.encryption_key:
        record["encryptedPayload"] = _encrypt(encrypted_data, settings.encryption_key)

    mutation = """
    mutation SetRecord($input: SetRecordInput!) {
        setRecord(input: $input) {
            id
        }
    }
    """

    variables = {"input": {"record": record}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            settings.laconicd_gql,
            json={"query": mutation, "variables": variables},
        )
        resp.raise_for_status()
        result = resp.json()

        if "errors" in result:
            logger.error("GraphQL errors writing record: %s", result["errors"])
            raise ValueError(f"Registry write failed: {result['errors']}")

        record_id = result.get("data", {}).get("setRecord", {}).get("id", "")
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
    # Build attribute filter
    attr_filter = {**attributes, "type": record_type}

    query = """
    query QueryRecords($attributes: [KeyValueInput!]) {
        queryRecords(attributes: $attributes) {
            id
            attributes {
                key
                value
            }
            encryptedPayload
        }
    }
    """

    kv_list = [{"key": k, "value": v} for k, v in attr_filter.items()]
    variables = {"attributes": kv_list}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            settings.laconicd_gql,
            json={"query": query, "variables": variables},
        )
        resp.raise_for_status()
        result = resp.json()

        if "errors" in result:
            logger.error("GraphQL errors querying records: %s", result["errors"])
            return []

    records = result.get("data", {}).get("queryRecords", [])
    decoded = []

    for record in records:
        entry: dict[str, Any] = {"id": record["id"]}

        # Flatten attributes
        for attr in record.get("attributes", []):
            entry[attr["key"]] = attr["value"]

        # Decrypt payload if present
        payload = record.get("encryptedPayload")
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
    """Delete records from laconicd registry by ID."""
    mutation = """
    mutation DeleteRecord($id: String!) {
        deleteRecord(id: $id) {
            success
        }
    }
    """

    async with httpx.AsyncClient(timeout=30.0) as client:
        for record_id in record_ids:
            resp = await client.post(
                settings.laconicd_gql,
                json={"query": mutation, "variables": {"id": record_id}},
            )
            if resp.status_code == 200:
                result = resp.json()
                if "errors" in result:
                    logger.error("Failed to delete record %s: %s", record_id, result["errors"])
                else:
                    logger.info("Deleted record %s", record_id)
