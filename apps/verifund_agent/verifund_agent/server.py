from contextlib import asynccontextmanager

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from commerce_core.db import configure_sqlite
from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_agent.auth import BearerAuthMiddleware
from verifund_agent.card import build_card
from verifund_agent.client import BuyerInternalClient
from verifund_agent.executor import VerifundExecutor
from verifund_agent.graph import build_graph
from verifund_agent.service import VerifundAgentService
from verifund_agent.settings import Settings


def create_app(
    settings: Settings | None = None,
    checkpointer=None,
) -> FastAPI:
    settings = settings or Settings()
    checkpointer = checkpointer or MemorySaver()
    engine = create_async_engine(settings.database_url)
    graph = build_graph(checkpointer)
    card = build_card(settings.public_url)
    buyer = BuyerInternalClient(
        settings.buyer_base_url,
        internal_token=settings.buyer_internal_token,
        timeout=settings.request_timeout_seconds,
    )
    service = VerifundAgentService(graph=graph, buyer=buyer)
    executor = VerifundExecutor(service)
    task_store = DatabaseTaskStore(engine=engine, create_table=True)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await configure_sqlite(engine)
            yield
        finally:
            await buyer.close()
            await engine.dispose()

    app = FastAPI(title="MarketMesh Verifund Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.graph = graph
    app.state.task_store = task_store
    app.state.buyer = buyer
    app.state.service = service
    app.add_middleware(
        BearerAuthMiddleware,
        token=settings.a2a_token,
        public_paths={
            "/health",
            "/ready",
            "/.well-known/agent-card.json",
        },
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "verifund-agent"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready", "service": "verifund-agent"}

    return app
