from scripts.dev import gateway_console_environment, gateway_environment


def test_gateway_environment_uses_one_port_and_prefixed_urls(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_PORT", "10000")
    monkeypatch.setenv("VERIFUND_MODE", "off")
    env = gateway_environment("scripted", "off")

    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "10000"
    assert env["PUBLIC_BASE_URL"] == "http://127.0.0.1:10000/sellers"
    assert env["BUYER_PUBLIC_BASE_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["BUYER_INTERNAL_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["SELLER_SHARED_URL"] == "http://127.0.0.1:10000/sellers"
    assert env["REGISTRY_URL"] == "http://127.0.0.1:10000/registry"
    assert env["ORCHESTRATOR_AGUI_URL"] == "http://127.0.0.1:10000/orchestrator"
    assert env["VERIFUND_URL"] == "http://127.0.0.1:10000/control-plane"
    assert env["VERIFUND_AGENT_URL"] == "http://127.0.0.1:10000/verifund-agent"

    # Collisions resolved: no bare fallback vars bleed between services.
    assert "DATABASE_URL" not in env
    assert "CHECKPOINT_PATH" not in env
    assert env["BUYER_DATABASE_URL"].startswith("sqlite+aiosqlite:///")


def test_gateway_environment_includes_the_agent_when_settlement_is_on(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GATEWAY_PORT", "10000")
    env = gateway_environment("scripted", "fake")

    assert env["VERIFUND_AGENT_DATABASE_URL"].startswith("sqlite+aiosqlite:///")
    assert env["VERIFUND_AGENT_CHECKPOINT_PATH"]
    assert env["VERIFUND_AGENT_CARD_URL"] == (
        "http://127.0.0.1:10000/verifund-agent/.well-known/agent-card.json"
    )


def test_gateway_console_environment_targets_the_gateway(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_PORT", "10000")
    env = gateway_console_environment("scripted", "off")

    assert env["BUYER_A2A_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["BUYER_AGUI_URL"] == "http://127.0.0.1:10000/buyer/agui"
    assert env["BUYER_API_URL"] == "http://127.0.0.1:10000/buyer"
    assert env["SELLER_SHARED_URL"] == "http://127.0.0.1:10000/sellers"
    assert env["ORCHESTRATOR_AGUI_URL"] == "http://127.0.0.1:10000/orchestrator"
    assert env["ORCHESTRATOR_URL"] == "http://127.0.0.1:10000/orchestrator"
    assert env["REGISTRY_URL"] == "http://127.0.0.1:10000/registry"
