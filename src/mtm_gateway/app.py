"""FastAPI application factory.

Creates the gateway app with:
- x402 payment middleware (LPS token on Solana)
- CORS configured properly (no wildcard with credentials)
- All route modules mounted
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtm_gateway.config import Settings, get_settings
from mtm_gateway.routes import devices, signals, status, subscriptions, wizards

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="MTM Gateway",
        description="Stateless x402-gated signal relay for MTM",
        version="0.1.0",
    )

    # CORS — restrict origins, no wildcard with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://x402.laconic.com",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-PAYMENT"],
    )

    # x402 payment middleware — gate endpoints with LPS micropayments
    # Only enable if wallet address is configured
    if settings.solana_wallet_address and settings.lps_mint_address:
        _add_x402_middleware(app, settings)
    else:
        logger.warning(
            "SOLANA_WALLET_ADDRESS or LPS_MINT_ADDRESS not set — x402 gating DISABLED"
        )

    # Mount routes
    app.include_router(status.router, tags=["status"])
    app.include_router(signals.router, tags=["signals"])
    app.include_router(subscriptions.router, tags=["subscriptions"])
    app.include_router(devices.router, tags=["devices"])
    app.include_router(wizards.router, tags=["wizards"])

    return app


def _make_resource_config(settings: Settings, price: str) -> dict:
    """Build an x402 ResourceConfig for an LPS-gated endpoint.

    Uses the 'exact' scheme on Solana mainnet, paying to the service wallet
    in the LPS SPL token.
    """
    from x402 import ResourceConfig

    rc = ResourceConfig(
        scheme="exact",
        pay_to=settings.solana_wallet_address,
        price=price,
        network=settings.solana_network,
    )
    return rc.model_dump()


def _add_x402_middleware(app: FastAPI, settings: Settings) -> None:
    """Configure x402 PaymentMiddlewareASGI for LPS payment gating.

    Each endpoint has its own price. Endpoints not listed here (/health,
    /lps/pricing, /wizards) are free.

    x402 RoutesConfig is a dict mapping path → { accepts: [ResourceConfig], extensions: {} }
    """
    try:
        from x402 import x402ResourceServer
        from x402.http.facilitator_client import HTTPFacilitatorClient
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI

        facilitator = HTTPFacilitatorClient(
            config={"url": settings.x402_facilitator_url}
        )
        server = x402ResourceServer(facilitator_clients=facilitator)

        def _route(price: str) -> dict:
            return {"accepts": [_make_resource_config(settings, price)], "extensions": {}}

        routes = {
            "/signals/buys": _route(settings.signal_price),
            "/signals/shorts": _route(settings.signal_price),
            "/signals/refresh": _route(settings.refresh_price),
            "/signals/receipt": _route(settings.receipt_price),
            "/devices/register": _route(settings.device_register_price),
            "/wizards/{wizard_id}/follow": _route(settings.wizard_follow_price),
            "/wizards/{wizard_id}/signal": _route(settings.wizard_signal_price),
            "/subscriptions/status": _route(settings.signal_price),
            "/subscriptions/verify-receipt": _route(settings.receipt_price),
        }

        app.add_middleware(
            PaymentMiddlewareASGI,
            routes=routes,
            server=server,
        )

        logger.info("x402 payment gating enabled with %d routes", len(routes))

    except ImportError:
        logger.error("x402 package not installed — payment gating DISABLED")
    except Exception:
        logger.exception("Failed to configure x402 middleware")
