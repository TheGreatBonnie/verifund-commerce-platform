from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import DatabaseTaskStore
from commerce_core.pricing import load_policy
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.auth import BearerAuthMiddleware
from seller_agent.card import build_agent_card
from seller_agent.executor import SellerExecutor
from seller_agent.planner import select_planner
from seller_agent.service import SellerService
from seller_agent.settings import Settings
from seller_agent.store import SellerStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    policy = load_policy(settings.profile_path)
    engine = create_async_engine(settings.database_url)
    store = SellerStore(engine)
    card = build_agent_card(policy, settings.public_base_url)
    task_store = DatabaseTaskStore(engine=engine, create_table=True)
    planner = select_planner(
        settings.llm_mode, settings.openrouter_api_key, settings.openrouter_model
    )
    service = SellerService(store=store, policy=policy, planner=planner)
    executor = SellerExecutor(service)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=card,
    )
    app = FastAPI(title=f"MarketMesh Seller — {policy.name}")
    app.state.settings = settings
    app.state.store = store
    app.state.policy = policy
    app.state.engine = engine
    app.state.service = service
    app.state.executor = executor
    app.add_middleware(
        BearerAuthMiddleware,
        token=settings.seller_token,
        public_paths={
            "/health",
            "/ready",
            "/metrics",
            "/.well-known/agent-card.json",
        },
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
    )

    @app.on_event("startup")
    async def startup() -> None:
        await store.create_schema()
        await store.seed_catalog(policy)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await engine.dispose()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "seller": policy.seller_id}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app
