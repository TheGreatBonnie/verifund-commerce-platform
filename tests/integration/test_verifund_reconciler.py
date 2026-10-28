from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_reconciler_run_route_requires_ops_and_records_a_run(api):
    refused = await api.post("/reconciler/run")
    assert refused.status_code == 401

    response = await api.post("/reconciler/run", headers=OPS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == 0
    assert "funding_checked" in body

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    runs = await repo.list_reconciler_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["stats"]["errors"] == 0
