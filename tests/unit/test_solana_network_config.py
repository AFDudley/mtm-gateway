"""Tests for SOLANA_NETWORK configurability in gateway.

Bug 2: gateway config.py Settings has no solana_network field.
app.py hardcodes network="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp".
"""

import pytest


class TestGatewaySettingsSolanaNetwork:
    """Gateway Settings must expose solana_network from env."""

    def test_settings_has_solana_network_field(self) -> None:
        """Settings dataclass must have a solana_network attribute."""
        from mtm_gateway.config import Settings

        s = Settings()
        assert hasattr(s, "solana_network"), (
            "Settings is missing solana_network field"
        )

    def test_settings_solana_network_reads_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """solana_network should come from SOLANA_NETWORK env var."""
        monkeypatch.setenv("SOLANA_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")
        from mtm_gateway.config import Settings

        s = Settings()
        assert s.solana_network == "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"

    def test_settings_solana_network_defaults_to_mainnet(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without SOLANA_NETWORK set, defaults to mainnet."""
        monkeypatch.delenv("SOLANA_NETWORK", raising=False)
        from mtm_gateway.config import Settings

        s = Settings()
        assert s.solana_network == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"


class TestGatewayAppUsesSolanaNetwork:
    """_make_resource_config must use settings.solana_network, not hardcode."""

    def test_resource_config_uses_settings_network(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The resource config network field must come from settings."""
        monkeypatch.setenv("SOLANA_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")
        monkeypatch.setenv("SOLANA_WALLET_ADDRESS", "testaddr")
        from mtm_gateway.app import _make_resource_config
        from mtm_gateway.config import Settings

        settings = Settings()
        rc = _make_resource_config(settings, "0.10")
        assert rc["network"] == "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", (
            "_make_resource_config should use settings.solana_network, "
            "not hardcode mainnet"
        )
