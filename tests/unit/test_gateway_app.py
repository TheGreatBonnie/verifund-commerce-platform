from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.app import MOUNT_PREFIXES, build_app


def make_sub(name: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started = True
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"service": name}

    return app


def test_build_app_mounts_every_prefix_and_runs_lifespans() -> None:
    names = (
        "orchestrator",
        "buyer",
        "registry",
        "seller",
        "control_plane",
        "verifund_agent",
    )
    subs = {name: make_sub(name) for name in names}
    app = build_app(subs)

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for prefix, name in MOUNT_PREFIXES.items():
            response = client.get(f"{prefix}/health")
            assert response.status_code == 200
            assert response.json() == {"service": name}
        for name in names:
            assert subs[name].state.started is True
