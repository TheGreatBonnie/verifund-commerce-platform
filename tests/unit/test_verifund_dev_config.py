from __future__ import annotations

import json
import urllib.error

from scripts import config, dev


def clear(monkeypatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_registry_environment_allows_default_seller_card_urls(monkeypatch):
    clear(
        monkeypatch,
        "ALLOWED_CARD_URLS",
        "NORTHWIND_PUBLIC_BASE_URL",
        "CIRCUITFORGE_PUBLIC_BASE_URL",
        "AURORA_PUBLIC_BASE_URL",
        "SUMMIT_TECH_PUBLIC_BASE_URL",
    )
    env = dev.registry_environment("scripted")
    assert json.loads(env["ALLOWED_CARD_URLS"]) == [
        "http://127.0.0.1:9201/.well-known/agent-card.json",
        "http://127.0.0.1:9202/.well-known/agent-card.json",
        "http://127.0.0.1:9203/.well-known/agent-card.json",
        "http://127.0.0.1:9204/.well-known/agent-card.json",
    ]


def test_wait_for_http_treats_auth_protected_404_as_ready(monkeypatch):
    def reject_request(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(dev.urllib.request, "urlopen", reject_request)

    dev.wait_for_http("console", "http://127.0.0.1:3000", timeout=0.1)


def test_mode_defaults_to_sandbox(monkeypatch):
    clear(monkeypatch, "VERIFUND_MODE")
    assert config.verifund_mode() == "sandbox"
    assert config.verifund_inspection_window_hours() == 24


def test_fake_mode_shortens_the_inspection_window(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "fake")
    clear(monkeypatch, "VERIFUND_INSPECTION_WINDOW_HOURS")
    assert config.verifund_inspection_window_hours() == 0


def test_explicit_inspection_window_wins(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "fake")
    monkeypatch.setenv("VERIFUND_INSPECTION_WINDOW_HOURS", "6")
    assert config.verifund_inspection_window_hours() == 6


def test_unknown_mode_falls_back_to_off(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "staging")
    assert config.verifund_mode() == "off"


def test_control_plane_url_prefers_verifund_control_plane_url(monkeypatch):
    monkeypatch.setenv("VERIFUND_CONTROL_PLANE_URL", "http://control-plane:9300/")
    clear(monkeypatch, "VERIFUND_URL")
    assert config.verifund_url() == "http://control-plane:9300"


def test_verifund_agent_defaults_and_tokens(monkeypatch):
    clear(
        monkeypatch,
        "VERIFUND_AGENT_PORT",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_CARD_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_AGENT_INTERNAL_TOKEN",
    )
    assert config.verifund_agent_port() == 9301
    assert config.verifund_agent_url() == "http://127.0.0.1:9301"
    assert (
        config.verifund_agent_card_url()
        == "http://127.0.0.1:9301/.well-known/agent-card.json"
    )
    assert config.verifund_agent_a2a_token() == "dev-verifund-agent-a2a"
    assert (
        config.verifund_agent_internal_token()
        == "dev-verifund-agent-internal"
    )


def test_verifund_agent_storage_defaults_survive_restarts(monkeypatch):
    clear(
        monkeypatch,
        "VERIFUND_AGENT_DATABASE_URL",
        "VERIFUND_AGENT_CHECKPOINT_PATH",
    )
    assert (
        config.verifund_agent_database_url()
        == "sqlite+aiosqlite:///./data/verifund-agent.db"
    )
    assert (
        config.verifund_agent_checkpoint_path()
        == "./data/verifund-agent-checkpoints.db"
    )
    monkeypatch.setenv(
        "VERIFUND_AGENT_CHECKPOINT_PATH", "/var/lib/verifund/checkpoints.db"
    )
    assert (
        config.verifund_agent_checkpoint_path()
        == "/var/lib/verifund/checkpoints.db"
    )


def test_payout_map_keeps_defaults_and_applies_overrides(monkeypatch):
    monkeypatch.setenv(
        "VERIFUND_SELLER_PAYOUT_EMAILS",
        '{"northwind-audio":"pay@northwind.test"}',
    )
    emails = json.loads(config.seller_payout_emails())
    assert emails["northwind-audio"] == "pay@northwind.test"
    assert emails["summit-tech"] == "seller-summit@example.com"
    assert len(emails) == 4


def test_invalid_payout_json_is_passed_through_for_startup_validation(monkeypatch):
    monkeypatch.setenv("VERIFUND_SELLER_PAYOUT_EMAILS", "{broken")
    assert config.seller_payout_emails() == "{broken"


def test_receipt_key_defaults(monkeypatch):
    clear(monkeypatch, "VERIFUND_RECEIPT_KEYS")
    assert json.loads(config.verifund_receipt_keys()) == {
        "dev-1": "dev-verifund-receipt-key"
    }


def test_off_mode_does_not_wire_the_buyer_to_the_control_plane(monkeypatch):
    clear(monkeypatch, "VERIFUND_URL", "VERIFUND_OPS_TOKEN", "BUYER_INTERNAL_TOKEN")
    buyer = dev.buyer_environment("scripted", "off")
    assert buyer["VERIFUND_MODE"] == "off"
    assert "VERIFUND_URL" not in buyer
    assert "BUYER_INTERNAL_TOKEN" not in buyer
    assert "VERIFUND_AGENT_INTERNAL_TOKEN" not in buyer

    orchestrator = dev.orchestrator_environment("scripted", "off")
    assert "VERIFUND_AGENT_URL" not in orchestrator
    assert "VERIFUND_AGENT_CARD_URL" not in orchestrator
    assert "VERIFUND_AGENT_A2A_TOKEN" not in orchestrator


def test_fake_mode_wires_buyer_seller_orchestrator_and_agent(monkeypatch):
    monkeypatch.setenv("VERIFUND_URL", "http://control:9300")
    monkeypatch.setenv("VERIFUND_OPS_TOKEN", "ops-token")
    monkeypatch.setenv("BUYER_INTERNAL_TOKEN", "internal-token")
    monkeypatch.setenv(
        "VERIFUND_AGENT_INTERNAL_TOKEN", "agent-internal-token"
    )
    monkeypatch.setenv("VERIFUND_AGENT_A2A_TOKEN", "agent-a2a-token")

    buyer = dev.buyer_environment("scripted", "fake")
    assert buyer["VERIFUND_URL"] == "http://control:9300"
    assert buyer["VERIFUND_OPS_TOKEN"] == "ops-token"
    assert buyer["BUYER_INTERNAL_TOKEN"] == "internal-token"
    assert (
        buyer["VERIFUND_AGENT_INTERNAL_TOKEN"] == "agent-internal-token"
    )

    seller = dev.seller_environment("scripted", config.SELLERS[0], "fake")
    assert seller["VERIFUND_MODE"] == "fake"
    assert seller["VERIFUND_URL"] == "http://control:9300"

    orchestrator = dev.orchestrator_environment("scripted", "fake")
    assert orchestrator["BUYER_INTERNAL_URL"] == config.buyer_url()
    assert orchestrator["BUYER_INTERNAL_TOKEN"] == "internal-token"
    assert orchestrator["VERIFUND_AGENT_URL"] == config.verifund_agent_url()
    assert (
        orchestrator["VERIFUND_AGENT_CARD_URL"]
        == config.verifund_agent_card_url()
    )
    assert orchestrator["VERIFUND_AGENT_A2A_TOKEN"] == "agent-a2a-token"

    agent = dev.verifund_agent_environment("fake")
    assert agent["VERIFUND_MODE"] == "fake"
    assert agent["PORT"] == "9301"
    assert agent["VERIFUND_AGENT_PORT"] == "9301"
    assert agent["VERIFUND_AGENT_URL"] == config.verifund_agent_url()
    assert agent["BUYER_INTERNAL_URL"] == config.buyer_url()
    assert agent["VERIFUND_AGENT_A2A_TOKEN"] == "agent-a2a-token"
    assert (
        agent["VERIFUND_AGENT_INTERNAL_TOKEN"] == "agent-internal-token"
    )
    assert (
        agent["VERIFUND_AGENT_DATABASE_URL"]
        == "sqlite+aiosqlite:///./data/verifund-agent.db"
    )
    assert (
        agent["VERIFUND_AGENT_CHECKPOINT_PATH"]
        == "./data/verifund-agent-checkpoints.db"
    )


def test_agent_environment_is_least_privilege(monkeypatch):
    monkeypatch.setenv("VERIFUND_OPS_TOKEN", "ops-secret")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "paypal-secret")
    monkeypatch.setenv("SELLER_NORTHWIND_TOKEN", "seller-secret")
    monkeypatch.setenv(
        "BUYER_SELLER_TOKENS", '{"northwind-audio":"seller-secret"}'
    )
    monkeypatch.setenv("BUYER_INTERNAL_TOKEN", "buyer-internal-secret")
    clear(
        monkeypatch,
        "VERIFUND_AGENT_PORT",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_AGENT_INTERNAL_TOKEN",
    )
    env = dev.verifund_agent_environment("fake")
    assert env["VERIFUND_MODE"] == "fake"
    assert env["PORT"] == "9301"
    assert env["VERIFUND_AGENT_PORT"] == "9301"
    assert env["VERIFUND_AGENT_URL"] == "http://127.0.0.1:9301"
    assert env["VERIFUND_AGENT_A2A_TOKEN"] == "dev-verifund-agent-a2a"
    assert (
        env["VERIFUND_AGENT_INTERNAL_TOKEN"]
        == "dev-verifund-agent-internal"
    )
    assert env["BUYER_INTERNAL_URL"] == config.buyer_url()
    for name in (
        "VERIFUND_OPS_TOKEN",
        "PAYPAL_CLIENT_SECRET",
        "SELLER_NORTHWIND_TOKEN",
        "BUYER_SELLER_TOKENS",
        "BUYER_INTERNAL_TOKEN",
    ):
        assert name not in env
    assert "ops-secret" not in env.values()
    assert "paypal-secret" not in env.values()
    assert "seller-secret" not in env.values()
    assert "buyer-internal-secret" not in env.values()


def test_registration_environment_has_admin_auth_but_no_runtime_secrets(
    monkeypatch,
):
    monkeypatch.setenv("REGISTRY_URL", "http://registry:9105")
    monkeypatch.setenv("REGISTRY_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("VERIFUND_OPS_TOKEN", "ops-secret")
    monkeypatch.setenv("VERIFUND_AGENT_INTERNAL_TOKEN", "agent-internal")
    monkeypatch.setenv("VERIFUND_AGENT_A2A_TOKEN", "agent-a2a")
    env = dev.verifund_registration_environment("fake")
    assert env["REGISTRY_URL"] == "http://registry:9105"
    assert env["REGISTRY_ADMIN_TOKEN"] == "admin-secret"
    assert env["VERIFUND_AGENT_ID"] == "verifund"
    assert env["VERIFUND_AGENT_CARD_URL"] == config.verifund_agent_card_url()
    for name in (
        "VERIFUND_AGENT_INTERNAL_TOKEN",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_OPS_TOKEN",
    ):
        assert name not in env
    assert "agent-internal" not in env.values()
    assert "agent-a2a" not in env.values()


def test_control_plane_environment_uses_fake_defaults(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "fake")
    clear(
        monkeypatch,
        "VERIFUND_INSPECTION_WINDOW_HOURS",
        "VERIFUND_ALLOW_PUBLIC_BIND",
    )
    env = dev.control_plane_environment("scripted", "fake")
    assert env["VERIFUND_MODE"] == "fake"
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_ALLOW_PUBLIC_BIND"] == "0"
    assert (
        json.loads(env["VERIFUND_SELLER_PAYOUT_EMAILS"])["northwind-audio"]
        == "seller-northwind@example.com"
    )
