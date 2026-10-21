from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint

from buyer_agent import console_api
from buyer_agent.graph import build_buyer_graph
from buyer_agent.services import BuyerServices, build_services
from buyer_agent.settings import Settings
from commerce_core.db import configure_sqlite


def create_app(
    settings: Settings,
    checkpointer,
    services: BuyerServices | None = None,
) -> FastAPI:
    owns_services = services is None
    engine = getattr(services, "engine", None) if services is not None else None
    if engine is None:
        engine = create_async_engine(settings.database_url)
    if services is None:
        services = build_services(settings, engine)
    graph = build_buyer_graph(services, checkpointer)
    app = FastAPI(title="MarketMesh Buyer")
    app.state.settings = settings
    app.state.engine = engine
    app.state.services = services
    app.state.graph = graph
    app.state.owns_services = owns_services
    add_langgraph_fastapi_endpoint(
        app,
        LangGraphAgent(
            name="marketmesh_buyer",
            graph=graph,
            emit_interrupt_outcome=True,
            config={"configurable": {"services": services}},
        ),
        path="/agui",
    )
    app.include_router(console_api.router)

    @app.on_event("startup")
    async def startup() -> None:
        await configure_sqlite(engine)
        store = getattr(services, "store", None)
        if store is not None:
            await store.create_schema()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        registry = getattr(services, "registry", None)
        if owns_services and registry is not None:
            await registry.close()
        await engine.dispose()

    return app
