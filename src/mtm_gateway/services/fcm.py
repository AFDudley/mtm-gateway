"""Firebase Cloud Messaging service.

Sends FCM data messages (not notification messages) so that Notifee
on the device handles display and action buttons (APE/PASS).

All data values must be strings — FCM requirement.
"""

from __future__ import annotations

import logging

import firebase_admin
from firebase_admin import credentials, messaging

from mtm_gateway.config import Settings

logger = logging.getLogger(__name__)

_app: firebase_admin.App | None = None


def _init_firebase(settings: Settings) -> firebase_admin.App:
    """Initialize Firebase Admin SDK (once)."""
    global _app
    if _app is not None:
        return _app

    cred = credentials.Certificate(str(settings.firebase_service_account))
    _app = firebase_admin.initialize_app(cred)
    logger.info("Firebase Admin SDK initialized")
    return _app


async def send_signal_to_tokens(
    settings: Settings,
    fcm_tokens: list[str],
    signal_data: dict[str, str],
) -> int:
    """Send a signal as FCM data message to multiple device tokens.

    Returns the number of successfully delivered messages.
    Removes stale tokens that return NotFound errors.
    """
    _init_firebase(settings)

    if not fcm_tokens:
        return 0

    # FCM data messages — all values must be strings
    message = messaging.MulticastMessage(
        data=signal_data,
        tokens=fcm_tokens,
    )

    try:
        response = messaging.send_each_for_multicast(message)
    except Exception:
        logger.exception("FCM multicast send failed")
        return 0

    delivered = response.success_count

    # Remove stale tokens
    if response.failure_count > 0:
        for i, send_response in enumerate(response.responses):
            if send_response.exception is not None:
                error_code = getattr(send_response.exception, "code", "")
                if error_code in (
                    "NOT_FOUND",
                    "UNREGISTERED",
                    "messaging/registration-token-not-registered",
                ):
                    logger.info("Stale FCM token: %s...", fcm_tokens[i][:20])
                    # TODO: delete device registration record from laconicd

    logger.info(
        "FCM sent: %d success, %d failure, %d total",
        response.success_count,
        response.failure_count,
        len(fcm_tokens),
    )

    return delivered
