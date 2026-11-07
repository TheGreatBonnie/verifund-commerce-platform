import hashlib
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from seller_agent.shared_auth import (
    SharedAuthMiddleware,
    SharedCallContextBuilder,
    StaticDemoCredentialVerifier,
)


class Verifier:
    async def verify(self, token, purpose="a2a:call"):
        if token == "good":
            return {"organization_id": "org-a", "agent_id": "agent-a",
                    "status": "active", "scopes": ["a2a:call"]}
        return None


def test_a2a_requires_a_valid_bearer():
    app = FastAPI()
    app.add_middleware(SharedAuthMiddleware, verifier=Verifier())

    @app.post("/shop/a2a")
    async def a2a():
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/shop/a2a").status_code == 401
    assert client.post(
        "/shop/a2a", headers={"Authorization": "Bearer bad"}
    ).status_code == 401
    assert client.post(
        "/shop/a2a", headers={"Authorization": "Bearer good"}
    ).status_code == 200


def test_card_route_is_public():
    app = FastAPI()
    app.add_middleware(SharedAuthMiddleware, verifier=Verifier())

    @app.get("/shop/.well-known/agent-card.json")
    async def card():
        return {"name": "Seller"}

    client = TestClient(app)
    assert client.get("/shop/.well-known/agent-card.json").status_code == 200


def test_call_context_carries_seller_and_caller():
    app = FastAPI()
    app.add_middleware(SharedAuthMiddleware, verifier=Verifier())

    @app.post("/{seller_id}/a2a")
    async def a2a(seller_id: str, request: Request):
        context = SharedCallContextBuilder().build(request)
        return {
            "seller_id": context.state["seller_id"],
            "caller": context.state["caller"],
        }

    client = TestClient(app)
    body = client.post(
        "/shop/a2a", headers={"Authorization": "Bearer good"}
    ).json()
    assert body["seller_id"] == "shop"
    assert body["caller"]["organization_id"] == "org-a"


def test_static_demo_verifier_reads_hashed_tokens(tmp_path):
    path = tmp_path / "demo-credentials.json"
    token = "dev-buyer-agent"
    path.write_text(json.dumps({
        "tokens": {
            hashlib.sha256(token.encode()).hexdigest(): {
                "organization_id": "org-buyer",
                "agent_id": "agent_buyer",
                "status": "active",
                "scopes": ["a2a:call"],
            },
            hashlib.sha256(b"seller-test-token").hexdigest(): {
                "organization_id": "org-seller",
                "agent_id": "agent_seller",
                "status": "active",
                "scopes": ["a2a:test"],
            },
        }
    }), encoding="utf-8")
    verifier = StaticDemoCredentialVerifier(path)
    import asyncio
    result = asyncio.run(verifier.verify(token))
    assert result is not None
    assert result["agent_id"] == "agent_buyer"
    assert asyncio.run(verifier.verify("wrong")) is None
    assert asyncio.run(
        verifier.verify("seller-test-token")
    ) is None
