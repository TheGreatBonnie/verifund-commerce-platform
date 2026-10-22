from __future__ import annotations

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import DatabaseTaskStore
from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint
from commerce_core.db import configure_sqlite
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from buyer_agent import console_api
from buyer_agent.card import build_buyer_agent_card
from buyer_agent.executor import BuyerExecutor
from buyer_agent.graph import build_buyer_graph
from buyer_agent.planner import select_buyer_planner
from buyer_agent.services import BuyerServices, build_services
from buyer_agent.settings import Settings

# Patch A2A JSON-RPC dispatcher to accept both PascalCase and lowercase method names
# The JavaScript SDK uses lowercase (e.g., "message/send") while Python SDK expects PascalCase (e.g., "SendMessage")
import a2a.server.routes.jsonrpc_dispatcher as _dispatcher
_original_method_to_model = _dispatcher.JsonRpcDispatcher.METHOD_TO_MODEL.copy()
_method_aliases = {
    'message/send': 'SendMessage',
    'message/stream': 'SendStreamingMessage',
    'tasks/get': 'GetTask',
    'tasks/list': 'ListTasks',
    'tasks/cancel': 'CancelTask',
    'tasks/pushNotificationConfig/set': 'CreateTaskPushNotificationConfig',
    'tasks/pushNotificationConfig/get': 'GetTaskPushNotificationConfig',
    'tasks/pushNotificationConfig/list': 'ListTaskPushNotificationConfigs',
    'tasks/pushNotificationConfig/delete': 'DeleteTaskPushNotificationConfig',
    'tasks/resubscribe': 'SubscribeToTask',
    'agent/auth/getExtendedCard': 'GetExtendedAgentCard',
}
_dispatcher.JsonRpcDispatcher.METHOD_TO_MODEL.update(
    {alias: _original_method_to_model[canonical] for alias, canonical in _method_aliases.items() if canonical in _original_method_to_model}
)


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
    planner = select_buyer_planner(
        settings.llm_mode,
        settings.nebius_api_key,
        settings.nebius_base_url,
        settings.nebius_model,
    )
    graph = build_buyer_graph(
        services=services,
        checkpointer=checkpointer,
        planner=planner,
    )
    app = FastAPI(title="MarketMesh Buyer")
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
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
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
