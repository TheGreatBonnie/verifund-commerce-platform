from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_defines_the_verifund_profile_services():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["verifund"]
    agent = compose["services"]["verifund-agent"]
    registration = compose["services"]["verifund-register"]

    assert service["environment"]["VERIFUND_MODE"] == "${VERIFUND_MODE:-sandbox}"
    assert "127.0.0.1:9300:9300" in service["ports"]
    assert service["environment"]["VERIFUND_ALLOW_PUBLIC_BIND"] == "1"
    assert (
        service["environment"]["VERIFUND_DATABASE_URL"]
        == "sqlite+aiosqlite:////app/data/verifund.db"
    )
    assert service["environment"]["VERIFUND_EVIDENCE_DIR"] == "/app/data/evidence"

    assert "127.0.0.1:9301:9301" in agent["ports"]
    assert agent["environment"]["BUYER_INTERNAL_URL"] == "http://buyer:9100"
    assert (
        agent["environment"]["VERIFUND_AGENT_URL"]
        == "http://verifund-agent:9301"
    )
    assert (
        agent["environment"]["VERIFUND_AGENT_A2A_TOKEN"]
        == "${VERIFUND_AGENT_A2A_TOKEN:-dev-verifund-agent-a2a}"
    )
    assert (
        agent["environment"]["VERIFUND_AGENT_INTERNAL_TOKEN"]
        == "${VERIFUND_AGENT_INTERNAL_TOKEN:-dev-verifund-agent-internal}"
    )
    assert (
        agent["environment"]["VERIFUND_AGENT_DATABASE_URL"]
        == "sqlite+aiosqlite:////app/data/verifund-agent.db"
    )
    assert (
        agent["environment"]["VERIFUND_AGENT_CHECKPOINT_PATH"]
        == "/app/data/verifund-agent-checkpoints.db"
    )
    assert "marketmesh-data:/app/data" in agent["volumes"]
    assert "VERIFUND_OPS_TOKEN" not in agent["environment"]
    assert "PAYPAL_CLIENT_SECRET" not in agent["environment"]
    assert "SELLER_TOKEN" not in agent["environment"]

    assert registration["command"] == "python -m verifund_agent.register"
    assert registration["restart"] == "no"
    assert registration["environment"]["REGISTRY_URL"] == "http://registry:9105"
    assert (
        registration["environment"]["REGISTRY_ADMIN_TOKEN"]
        == "${REGISTRY_ADMIN_TOKEN:-dev-registry-admin}"
    )
    assert (
        registration["environment"]["VERIFUND_AGENT_CARD_URL"]
        == "http://verifund-agent:9301/.well-known/agent-card.json"
    )


def test_compose_wires_settlement_settings_into_existing_services():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    registry = compose["services"]["registry"]["environment"]
    assert "verifund-agent" in registry["ALLOWED_CARD_HOSTS"]

    buyer = compose["services"]["buyer"]["environment"]
    assert buyer["VERIFUND_MODE"] == "${VERIFUND_MODE:-sandbox}"
    assert buyer["VERIFUND_URL"] == "http://verifund:9300"
    assert (
        buyer["BUYER_INTERNAL_TOKEN"]
        == "${BUYER_INTERNAL_TOKEN:-dev-buyer-internal}"
    )
    assert (
        buyer["VERIFUND_AGENT_INTERNAL_TOKEN"]
        == "${VERIFUND_AGENT_INTERNAL_TOKEN:-dev-verifund-agent-internal}"
    )

    seller = compose["services"]["seller-shared"]["environment"]
    assert seller["VERIFUND_MODE"] == "${VERIFUND_MODE:-sandbox}"
    assert seller["VERIFUND_URL"] == "http://verifund:9300"
    assert seller["SELLER_CONFIG_SOURCE"] == "shared"
    assert (
        seller["SELLER_SHARED_DB_URL"]
        == "sqlite+aiosqlite:////app/data/sellers.db"
    )
    assert (
        seller["SELLER_INTERNAL_TOKEN"]
        == "${SELLER_INTERNAL_TOKEN:-dev-seller-internal}"
    )
    assert seller["PUBLIC_BASE_URL"] == "http://seller-shared:9200"

    orchestrator = compose["services"]["orchestrator"]["environment"]
    assert orchestrator["BUYER_INTERNAL_URL"] == "http://buyer:9100"
    assert (
        orchestrator["BUYER_INTERNAL_TOKEN"]
        == "${BUYER_INTERNAL_TOKEN:-dev-buyer-internal}"
    )
    assert orchestrator["VERIFUND_MODE"] == "${VERIFUND_MODE:-sandbox}"
    assert orchestrator["VERIFUND_AGENT_URL"] == "http://verifund-agent:9301"
    assert (
        orchestrator["VERIFUND_AGENT_CARD_URL"]
        == "http://verifund-agent:9301/.well-known/agent-card.json"
    )
    assert (
        orchestrator["VERIFUND_AGENT_A2A_TOKEN"]
        == "${VERIFUND_AGENT_A2A_TOKEN:-dev-verifund-agent-a2a}"
    )

    console = compose["services"]["console"]["environment"]
    assert console["VERIFUND_MODE"] == "${VERIFUND_MODE:-sandbox}"


def test_dockerfile_copies_the_verifund_services():
    text = (ROOT / "Dockerfile.python").read_text()
    assert (
        "COPY apps/verifund_control_plane ./apps/verifund_control_plane" in text
    )
    assert "COPY apps/verifund_agent ./apps/verifund_agent" in text


def test_makefile_exposes_verifund_targets():
    text = (ROOT / "Makefile").read_text()
    for target in (
        "verifund-smoke",
        "verifund-e2e",
        "verifund-demo",
        "verifund-preflight",
        "verifund-sandbox-smoke",
    ):
        assert f"{target}:" in text
    assert "rm -rf data/evidence" in text


def test_env_example_documents_every_verifund_setting():
    text = (ROOT / ".env.example").read_text()
    for name in (
        "VERIFUND_MODE",
        "VERIFUND_PORT",
        "VERIFUND_AGENT_PORT",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_CARD_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_AGENT_INTERNAL_TOKEN",
        "VERIFUND_AGENT_TIMEOUT_SECONDS",
        "VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS",
        "VERIFUND_AGENT_DATABASE_URL",
        "VERIFUND_AGENT_CHECKPOINT_PATH",
        "VERIFUND_CONTROL_PLANE_URL",
        "VERIFUND_PUBLIC_BASE_URL",
        "VERIFUND_CONSOLE_BASE_URL",
        "VERIFUND_ALLOW_PUBLIC_BIND",
        "VERIFUND_OPS_TOKEN",
        "BUYER_INTERNAL_TOKEN",
        "VERIFUND_SELLER_TOKEN_SECRET",
        "VERIFUND_LINK_SECRET",
        "VERIFUND_RECEIPT_KEYS",
        "VERIFUND_RECEIPT_ACTIVE_KID",
        "VERIFUND_DATABASE_URL",
        "VERIFUND_EVIDENCE_DIR",
        "VERIFUND_MAX_EVIDENCE_BYTES",
        "VERIFUND_TIMEOUT_SECONDS",
        "VERIFUND_SELLER_TOKEN_TTL_HOURS",
        "VERIFUND_CHECKOUT_LINK_TTL_MINUTES",
        "VERIFUND_RETURN_LINK_TTL_HOURS",
        "VERIFUND_EVIDENCE_DEADLINE_HOURS",
        "VERIFUND_INSPECTION_WINDOW_HOURS",
        "VERIFUND_FUNDING_TIMEOUT_HOURS",
        "VERIFUND_PAYOUT_ALERT_HOURS",
        "PAYPAL_ENV",
        "PAYPAL_API_BASE",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_WEBHOOK_ID",
        "PAYPAL_PLATFORM_EMAIL",
        "PAYPAL_BUYER_EMAIL",
        "VERIFUND_SELLER_PAYOUT_EMAILS",
        "VERIFUND_RECONCILER_ENABLED",
        "VERIFUND_RECONCILER_PENDING_SECONDS",
        "VERIFUND_RECONCILER_DEADLINE_SECONDS",
        "VERIFUND_RECONCILER_RECEIPT_SECONDS",
        "VERIFUND_FAKE_SCENARIO",
        "VERIFUND_FAKE_WEBHOOK_SECRET",
        "VERIFUND_AUTO_EVIDENCE",
        "VERIFUND_EVIDENCE_RETRY_SECONDS",
    ):
        assert f"{name}=" in text, name


def test_gitignore_excludes_evidence_and_coverage_artifacts():
    text = (ROOT / ".gitignore").read_text()
    assert "data/evidence/" in text
    assert ".coverage" in text

