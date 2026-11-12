"""The orchestrator must reach seller cards on the deployed gateway.

``fetch_agent_card`` refuses hosts outside an allowlist. The orchestrator
calls sellers by the card URL the registry published, so it has to pass an
allowlist that includes the deployed gateway instead of the local-only
default.
"""

from __future__ import annotations

import json

import pytest
from a2a.types.a2a_pb2 import Role
from commerce_core.a2a_parts import make_message
from orchestrator_agent import agent, mediation
from orchestrator_agent.settings import Settings


def test_orchestrator_settings_read_allowed_card_hosts(monkeypatch) -> None:
    monkeypatch.setenv(
        "ALLOWED_CARD_HOSTS", json.dumps(["gw.example.com", "127.0.0.1"])
    )

    settings = Settings()

    assert "gw.example.com" in settings.allowed_card_hosts


def test_orchestrator_settings_read_buyer_a2a_url(monkeypatch) -> None:
    monkeypatch.setenv("BUYER_A2A_URL", "https://gw.example.com/buyer")

    settings = Settings()

    assert settings.buyer_a2a_url == "https://gw.example.com/buyer"


async def test_a2a_send_uses_the_configured_card_hosts(monkeypatch) -> None:
    captured: dict = {}

    async def fake_fetch(url, *, client=None, allowed_hosts=()):
        captured["url"] = url
        captured["allowed_hosts"] = allowed_hosts
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(mediation, "fetch_agent_card", fake_fetch)
    mediation.set_card_hosts(("gw.example.com",))
    try:
        with pytest.raises(RuntimeError):
            await mediation._a2a_send(
                "https://gw.example.com/sellers/northwind-audio",
                make_message(
                    role=Role.ROLE_USER, text="hello", context_id="ctx-1"
                ),
            )
    finally:
        mediation.set_card_hosts(mediation.DEFAULT_CARD_HOSTS)

    assert captured["allowed_hosts"] == ("gw.example.com",)


def test_build_agent_configures_the_card_hosts(monkeypatch) -> None:
    captured: dict = {}

    def fake_set(hosts) -> None:
        captured["hosts"] = hosts

    monkeypatch.setattr(agent, "set_card_hosts", fake_set)
    settings = Settings(allowed_card_hosts=("gw.example.com",))

    agent.build_agent(settings)

    assert captured["hosts"] == ("gw.example.com",)
