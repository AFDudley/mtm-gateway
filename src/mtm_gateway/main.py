"""Gateway entrypoint.

Starts the FastAPI server with optional FCM push scheduler.
"""

from __future__ import annotations

import logging
import uuid

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from mtm_gateway.app import create_app
from mtm_gateway.config import get_settings
from mtm_gateway.services import backtest_client
from mtm_gateway.services.fcm import send_signal_to_tokens
from mtm_gateway.services.laconic_registry import query_records

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = create_app()


async def _signal_push_cycle() -> None:
    """Periodic job: fetch fresh signals, push to all registered devices.

    Runs on the same schedule as k_solana_backtest (default 24h).
    """
    settings = get_settings()
    logger.info("Signal push cycle starting")

    try:
        # Fetch fresh buy signals from upstream
        data = await backtest_client.fetch_buy_signals(settings)
        raw_signals = data.get("signals", [])

        if not raw_signals:
            logger.info("No signals from backtest service")
            return

        # Query all registered devices from laconicd
        device_records = await query_records(
            settings=settings,
            record_type="DeviceRegistration",
            attributes={},
        )

        if not device_records:
            logger.info("No registered devices")
            return

        # Collect FCM tokens
        fcm_tokens = [r["fcmToken"] for r in device_records if r.get("fcmToken")]

        # Send top signal as push notification
        top = raw_signals[0]
        n = top.get("n_strategies", 0)
        strategies = top.get("strategies_firing", [])
        token = top.get("token", "UNKNOWN")

        signal_data = {
            "signalId": f"sig_{uuid.uuid4().hex[:12]}",
            "asset": f"${token}",
            "action": "BUY",
            "confidence": str(round(n / 19, 2)),
            "reason": ", ".join(strategies[:3]) if strategies else "Consensus signal",
            "duration": "24h",
        }

        delivered = await send_signal_to_tokens(settings, fcm_tokens, signal_data)
        logger.info(
            "Signal push cycle complete: signal=%s delivered=%d/%d",
            token,
            delivered,
            len(fcm_tokens),
        )

    except Exception:
        logger.exception("Signal push cycle failed")


@app.on_event("startup")
async def startup() -> None:
    settings = get_settings()

    # Start FCM push scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _signal_push_cycle,
        "interval",
        hours=settings.signal_cycle_interval_hours,
        id="signal_push_cycle",
    )
    scheduler.start()
    logger.info("Signal push scheduler started (every %dh)", settings.signal_cycle_interval_hours)


if __name__ == "__main__":
    uvicorn.run(
        "mtm_gateway.main:app",
        host="0.0.0.0",
        port=8091,
        reload=False,
    )
