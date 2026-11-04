import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn


@asynccontextmanager
async def run_uvicorn(app, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            try:
                response = await client.get(f"http://127.0.0.1:{port}/health")
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def seller_runtime(tmp_path):
    from seller_agent.server import create_app
    from seller_agent.settings import Settings

    settings = Settings(
        _env_file=None,
        verifund_mode="off",
        service_name="Northwind Audio",
        host="127.0.0.1",
        port=9201,
        public_base_url="http://127.0.0.1:9201",
        profile_path=Path(
            "apps/seller_agent/seller_agent/profiles/northwind.yaml"
        ),
        seller_token="test-seller-token",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}",
        llm_mode="scripted",
        nebius_api_key=None,
        nebius_base_url="https://api.tokenfactory.us-central1.nebius.com/v1/",
        nebius_model="deepseek-ai/DeepSeek-V4-Flash-0731",
    )
    app = create_app(settings)
    async with run_uvicorn(app, 9201) as base_url:
        yield base_url, app


@pytest.fixture
async def seller_server(seller_runtime):
    return seller_runtime[0]
