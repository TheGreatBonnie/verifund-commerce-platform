import asyncio
import socket
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
import pytest
import uvicorn


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@asynccontextmanager
async def run_uvicorn(app, port: int | None = None):
    if port is None:
        port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    started = False
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                if task.done():
                    break
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    if response.status_code == 200:
                        started = True
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError("server did not start")
            if not started:
                exc = task.exception() if task.done() else None
                raise RuntimeError("server did not start") from exc
        # Discover actual bound port (supports port=0-style ephemeral).
        actual_port = port
        try:
            if server.servers and server.servers[0].sockets:
                actual_port = int(server.servers[0].sockets[0].getsockname()[1])
        except Exception:  # noqa: BLE001
            pass
        yield f"http://127.0.0.1:{actual_port}"
    finally:
        server.should_exit = True
        if not task.done():
            task.cancel()
        with suppress(
            BaseException,
        ):
            await task


@pytest.fixture
async def seller_runtime(tmp_path):
    from seller_agent.server import create_app
    from seller_agent.settings import Settings

    port = _free_port()
    settings = Settings(
        _env_file=None,
        verifund_mode="off",
        service_name="Northwind Audio",
        host="127.0.0.1",
        port=port,
        public_base_url=f"http://127.0.0.1:{port}",
        profile_path=Path(
            "docs/templates/northwind.yaml"
        ),
        seller_token="test-seller-token",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}",
        llm_mode="scripted",
        nebius_api_key=None,
        nebius_base_url="https://api.tokenfactory.us-central1.nebius.com/v1/",
        nebius_model="deepseek-ai/DeepSeek-V4-Flash-0731",
    )
    app = create_app(settings)
    async with run_uvicorn(app, port) as base_url:
        yield base_url, app


@pytest.fixture
async def seller_server(seller_runtime):
    return seller_runtime[0]
