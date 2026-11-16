from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint
from commerce_core.db import configure_database
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from buyer_agent import console_api, settlement_api
from buyer_agent.card import build_buyer_agent_card
from buyer_agent.executor import BuyerExecutor
from buyer_agent.graph import build_buyer_graph
from buyer_agent.planner import select_buyer_planner
from buyer_agent.services import BuyerServicesLike, build_services
from buyer_agent.settings import Settings


async def run_registry_poller(
    registry_client: Any,
    *,
    poll_interval: float,
    sleep: Any = asyncio.sleep,
) -> None:
    """Poll the registry until it answers, then on the normal cadence.

    The registry is served by this same process, so its socket is not bound
    until the ASGI startup completes: the first poll cannot land and the
    edge answers 502. Retry on a short backoff until the registry answers
    instead of failing the poll outright.
    """
    logger = logging.getLogger(__name__)
    delay = 1.0
    failures = 0
    while True:
        if await registry_client.refresh_registry():
            failures = 0
            delay = 1.0
            await sleep(poll_interval)
            continue
        failures += 1
        if failures >= 3:
            logger.warning("registry poll failed %d times in a row", failures)
        else:
            logger.info("registry not reachable yet; retrying in %.1fs", delay)
        await sleep(delay)
        delay = min(delay * 2, poll_interval)


def create_app(
    settings: Settings,
    checkpointer,
    services: BuyerServicesLike | None = None,
) -> FastAPI:
    owns_services = services is None
    engine = getattr(services, "engine", None) if services is not None else None
    if engine is None:
        engine = create_async_engine(settings.database_url)
    if services is None:
        services = build_services(settings, engine)
    planner = select_buyer_planner(
        settings.llm_mode,
        settings.nebius_api_key,
        settings.nebius_base_url,
        settings.buyer_model,
    )
    graph = build_buyer_graph(
        services=services,
        checkpointer=checkpointer,
        planner=planner,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        poll_task = None
        try:
            await configure_database(engine)
            store = getattr(services, "store", None)
            if store is not None:
                await store.create_schema()
            registry_client = getattr(services, "registry", None)
            if registry_client is not None:
                poll_interval = getattr(settings, "buyer_registry_poll_seconds", 30)
                poll_task = asyncio.create_task(
                    run_registry_poller(
                        registry_client,
                        poll_interval=poll_interval,
                    )
                )
            yield
        finally:
            if poll_task is not None:
                poll_task.cancel()
            registry = getattr(services, "registry", None)
            if owns_services and registry is not None:
                await registry.close()
            await engine.dispose()

    app = FastAPI(title="MarketMesh Buyer", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.services = services
    app.state.graph = graph
    app.state.owns_services = owns_services

    card = build_buyer_agent_card(settings.public_base_url)
    task_store = DatabaseTaskStore(engine=engine, create_table=True)
    executor = BuyerExecutor(
        services=services,
        settings=settings,
        checkpointer=checkpointer,
        graph=graph,
    )
    app.state.executor = executor
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(
            handler,
            rpc_url="/a2a",
            # The console uses the A2A 0.3 JavaScript client (lowercase
            # methods such as "message/send"). Keep the 1.0 endpoint and add
            # the SDK's built-in 0.3 compatibility adapter alongside it.
            enable_v0_3_compat=True,
        ),
    )

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
    app.include_router(settlement_api.router)

    return app
