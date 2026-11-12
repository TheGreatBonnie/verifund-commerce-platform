import httpx
import pytest
from gateway.__main__ import gateway_stack


@pytest.mark.asyncio
async def test_each_prefix_reaches_its_own_service(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VERIFUND_MODE", "off")
    monkeypatch.setenv("BUYER_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/buyer.db")
    monkeypatch.setenv("BUYER_CHECKPOINT_PATH", str(tmp_path / "buyer-checkpoints.db"))
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/registry.db")
    monkeypatch.setenv("SELLER_SHARED_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    monkeypatch.setenv("SELLER_CHECKPOINT_PATH", str(tmp_path / "seller-checkpoints.db"))
    monkeypatch.setenv("SELLER_CONFIG_SOURCE", "shared")
    monkeypatch.setenv("VERIFUND_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/verifund.db")
    monkeypatch.setenv("VERIFUND_AGENT_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/agent.db")
    monkeypatch.setenv("VERIFUND_AGENT_CHECKPOINT_PATH", str(tmp_path / "agent-checkpoints.db"))
    monkeypatch.setenv("VERIFUND_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("ORCHESTRATOR_SESSION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/sessions.db")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("BUYER_PUBLIC_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("VERIFUND_AGENT_URL", "http://127.0.0.1")
    monkeypatch.setenv("VERIFUND_URL", "http://127.0.0.1")
    monkeypatch.setenv("BUYER_INTERNAL_URL", "http://127.0.0.1")
    monkeypatch.setenv("SELLER_SHARED_URL", "http://127.0.0.1")
    monkeypatch.setenv("ALLOWED_CARD_HOSTS", '["127.0.0.1", "localhost"]')

    async with gateway_stack() as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            orchestrator = await client.get("/orchestrator/health")
            assert orchestrator.json()["service"] == "orchestrator"

            agent = await client.get("/verifund-agent/health")
            assert agent.json()["service"] == "verifund-agent"

            buyer = await client.get("/buyer/health")
            assert buyer.status_code == 200

            registry = await client.get("/registry/health")
            assert registry.status_code == 200

            seller = await client.get("/sellers/health")
            assert seller.status_code == 200

            control_plane = await client.get("/control-plane/health")
            assert control_plane.status_code == 200
