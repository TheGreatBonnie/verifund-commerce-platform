from __future__ import annotations

import json

import httpx
import pytest
from buyer_agent.server import create_app
from buyer_agent.settings import Settings
from langgraph.checkpoint.memory import MemorySaver

from commerce_core.a2a_parts import make_message, first_envelope
from commerce_core.cards import fetch_agent_card
from a2a.types.a2a_pb2 import Role, SendMessageRequest
from tests.support.a2a import make_client
from tests.support.fake_buyer import FakeServices


@pytest.fixture
async def mediated_buyer_server(tmp_path, seller_runtime):
    # Keep only the live Northwind seller in the fake registry.
    services = FakeServices()
    keep = {"northwind-audio"}
    services.registry._endpoints = {
        k: v for k, v in services.registry._endpoints.items() if k in keep
    }
    settings = Settings(
        host="127.0.0.1",
        port=9120,
        public_base_url="http://127.0.0.1:9120",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}",
        checkpoint_path=tmp_path / "checkpoints.db",
        llm_mode="scripted",
    )
    app = create_app(settings, MemorySaver(), services)
    from tests.support.servers import run_uvicorn

    async with run_uvicorn(app, 9120) as base_url:
        yield base_url, app


@pytest.mark.asyncio
async def test_gate_single_seller_call_round_trip(mediated_buyer_server, seller_runtime):
    base_url, app = mediated_buyer_server
    services = app.state.services
    card = await fetch_agent_card(f"{base_url}/.well-known/agent-card.json")
    client = await make_client(card, "")
    try:
        msg = make_message(
            role=Role.ROLE_USER,
            text=json.dumps({"brief": "Buy 12 Nimbus NC-700 ANC headsets, budget $3400, 14 days, 24mo warranty, 30d returns."}),
            context_id="gate-1",
        )
        frames = []
        async for ev in client.send_message(SendMessageRequest(message=msg)):
            frames.append(ev)

        # Find the seller_call INPUT_REQUIRED pause.
        seller_call = None
        for f in frames:
            kind = f.WhichOneof("payload")
            obj = f.task if kind == "task" else (f.status_update if kind == "status_update" else None)
            if obj is None:
                continue
            # inspect status message parts
            status_msg = obj.status.message if hasattr(obj, "status") else None
            if status_msg is None:
                continue
            for p in status_msg.parts:
                if p.HasField("text"):
                    try:
                        v = json.loads(p.text)
                    except Exception:
                        continue
                    if isinstance(v, dict) and v.get("reason") == "seller_call":
                        seller_call = v
        assert seller_call is not None, "buyer did not pause with seller_call INPUT_REQUIRED"
        assert seller_call["seller_task_id"] is None
        assert seller_call["seller_context_id"] == "gate-1"
        task_id = seller_call["task_id"]
        seller_id = seller_call["seller_id"]
        assert seller_id == "northwind-audio"

        # Mediate through orchestrator FunctionTool (real seller on 9201).
        from orchestrator_agent.mediation import mediate_seller_call

        endpoint = services.registry.endpoint(seller_id)
        result = await mediate_seller_call(
            buyer_task_id=task_id,
            seller_card_url=endpoint.card_url,
            buyer_a2a_url=base_url,
            seller_request=seller_call["request"],
            seller_token="test-seller-token",
        )
        assert "error" not in result, result
        assert result["seller_result"]["offers"], "no offer round-tripped from seller"

        # The mediated offer survived the A2A round trip semantically.
        assert result["seller_result"]["offers"][0]["seller_id"] == seller_id
        assert result["seller_result"]["offers"][0]["total_cents"] > 0

        # Buyer checkpoint resumed and advanced (no longer at the original rfq pause).
        snap = await app.state.graph.aget_state(
            {"configurable": {"thread_id": task_id, "services": services}}
        )
        assert snap.next in (("process_seller",), ("await_approval",), ())
    finally:
        await client.close()
