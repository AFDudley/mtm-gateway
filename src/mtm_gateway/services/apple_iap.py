"""Apple App Store Server API v2 receipt validation.

Flow:
1. Frontend sends `transactionReceipt` (JWS signed transaction from StoreKit 2)
2. Gateway verifies the JWS signature using Apple's root certificate chain
3. Extracts product_id, original_transaction_id, and purchase amount
4. Checks laconicd registry for duplicate transaction (prevents double-minting)
5. Transfers LPS from service wallet to user's wallet
6. Stores the transaction ID in laconicd registry as processed
7. Returns LPS amount and tx signature to frontend

Apple's JWS format: header.payload.signature
- Header contains x5c certificate chain
- Payload is the signed transaction info
- Signature is over the header+payload

Reference: https://developer.apple.com/documentation/appstoreserverapi
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from mtm_gateway.config import Settings

logger = logging.getLogger(__name__)

# Apple's root certificate OID for App Store receipts
APPLE_ROOT_CA_G3_FINGERPRINTS = {
    # Apple Root CA - G3 (SHA-256 fingerprint)
    "b0b1730ecbc7ff4505142c49f1295e6eda6bcaed7e2c68c5be91b5a11001f024",
}

# Product ID → LPS amount mapping (matches TIER_PRICE in src/types/index.ts)
PRODUCT_LPS_AMOUNT: dict[str, Decimal] = {
    "mtm_starter_monthly": Decimal("29"),
    "mtm_pro_monthly": Decimal("79"),
    "mtm_elite_monthly": Decimal("199"),
    "mtm_signal_refresh": Decimal("0.50"),
}

# Apple environments
APPLE_PRODUCTION = "Production"
APPLE_SANDBOX = "Sandbox"


@dataclass
class ValidatedPurchase:
    original_transaction_id: str
    product_id: str
    lps_amount: Decimal
    environment: str
    purchase_date_ms: int


def verify_jws_transaction(jws_token: str) -> ValidatedPurchase:
    """Verify an Apple JWS-signed transaction and extract purchase info.

    The JWS token from StoreKit 2 contains:
    - Header with x5c certificate chain
    - Payload with transaction details
    - Signature verified against Apple's certificate chain

    Raises ValueError if verification fails.
    """
    # Split JWS into parts
    parts = jws_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWS format: expected 3 parts")

    # Decode header to get certificate chain
    header_b64 = parts[0]
    # Add padding if needed
    header_b64 += "=" * (4 - len(header_b64) % 4) if len(header_b64) % 4 else ""
    header = json.loads(base64.urlsafe_b64decode(header_b64))

    x5c_chain = header.get("x5c", [])
    if not x5c_chain or len(x5c_chain) < 2:
        raise ValueError("Missing or incomplete x5c certificate chain")

    # Verify certificate chain
    _verify_certificate_chain(x5c_chain)

    # Extract the leaf certificate's public key for signature verification
    leaf_cert_der = base64.b64decode(x5c_chain[0])
    leaf_cert = x509.load_der_x509_certificate(leaf_cert_der)
    public_key = leaf_cert.public_key()

    # Verify the JWS signature using the leaf certificate
    try:
        # PyJWT handles the signature verification
        payload = jwt.decode(
            jws_token,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": False, "verify_iss": False},
        )
    except jwt.InvalidSignatureError:
        raise ValueError("JWS signature verification failed")
    except jwt.DecodeError as e:
        raise ValueError(f"JWS decode error: {e}")

    # Extract transaction info from payload
    product_id = payload.get("productId", "")
    original_transaction_id = payload.get("originalTransactionId", "")
    environment = payload.get("environment", APPLE_PRODUCTION)
    purchase_date_ms = payload.get("purchaseDateMs") or payload.get("purchaseDate", 0)

    if not product_id or not original_transaction_id:
        raise ValueError("Missing productId or originalTransactionId in transaction")

    lps_amount = PRODUCT_LPS_AMOUNT.get(product_id)
    if lps_amount is None:
        raise ValueError(f"Unknown product ID: {product_id}")

    return ValidatedPurchase(
        original_transaction_id=original_transaction_id,
        product_id=product_id,
        lps_amount=lps_amount,
        environment=environment,
        purchase_date_ms=int(purchase_date_ms),
    )


def _verify_certificate_chain(x5c_chain: list[str]) -> None:
    """Verify the x5c certificate chain traces back to Apple's root CA.

    Chain order: [leaf, intermediate, ..., root]
    - Each cert is signed by the next one in the chain
    - The root cert's fingerprint must match Apple's known root CA
    """
    certs = []
    for cert_b64 in x5c_chain:
        cert_der = base64.b64decode(cert_b64)
        cert = x509.load_der_x509_certificate(cert_der)
        certs.append(cert)

    if len(certs) < 2:
        raise ValueError("Certificate chain too short")

    # Verify chain: each cert is signed by the next
    for i in range(len(certs) - 1):
        child = certs[i]
        parent = certs[i + 1]

        try:
            parent.public_key().verify(
                child.signature,
                child.tbs_certificate_bytes,
                ec.ECDSA(child.signature_hash_algorithm),
            )
        except Exception:
            raise ValueError(f"Certificate chain verification failed at position {i}")

    # Verify root certificate fingerprint
    root_cert = certs[-1]
    root_fingerprint = root_cert.fingerprint(hashes.SHA256()).hex()
    if root_fingerprint not in APPLE_ROOT_CA_G3_FINGERPRINTS:
        raise ValueError(
            f"Root certificate fingerprint {root_fingerprint} " "does not match Apple Root CA"
        )

    # Check leaf certificate validity (allow 10 min clock skew)
    from datetime import UTC, datetime, timedelta

    leaf = certs[0]
    now = datetime.now(UTC)
    skew = timedelta(minutes=10)
    if now + skew < leaf.not_valid_before_utc:
        raise ValueError("Leaf certificate is not yet valid")
    if now - skew > leaf.not_valid_after_utc:
        raise ValueError("Leaf certificate has expired")


def generate_app_store_jwt(settings: Settings) -> str:
    """Generate a JWT for authenticating with the App Store Server API.

    Used for server-to-server calls like looking up transaction history.
    The JWT is signed with the API key downloaded from App Store Connect.

    Required settings:
    - apple_key_id: API key ID
    - apple_issuer_id: Issuer ID from App Store Connect
    - apple_private_key_path: Path to the .p8 private key file
    """
    now = int(time.time())

    with open(settings.apple_private_key_path) as f:
        private_key = f.read()

    payload = {
        "iss": settings.apple_issuer_id,
        "iat": now,
        "exp": now + 3600,  # 1 hour
        "aud": "appstoreconnect-v1",
        "bid": settings.apple_bundle_id,
    }

    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )

    return token
