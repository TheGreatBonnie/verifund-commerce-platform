from __future__ import annotations

from contextlib import asynccontextmanager

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from commerce_core.pricing import load_policy
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.auth import BearerAuthMiddleware
from seller_agent.card import build_agent_card
from seller_agent.executor import SellerExecutor
from seller_agent.planner import select_seller_planner
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
    planner = select_seller_planner(
        settings.llm_mode,
        settings.nebius_api_key,
        settings.nebius_base_url,
        settings.nebius_model,
    )
    service = SellerService(store=store, policy=policy, planner=planner)
    executor = SellerExecutor(service)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await store.create_schema()
            await store.seed_catalog(policy)
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title=f"MarketMesh Seller — {policy.name}", lifespan=lifespan
    )
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
        jsonrpc_routes=create_jsonrpc_routes(
            handler,
            rpc_url="/a2a",
            # The console uses the A2A 0.3 JavaScript client (lowercase
            # methods such as "message/send"). Keep the 1.0 endpoint and add
            # the SDK's built-in 0.3 compatibility adapter alongside it.
            enable_v0_3_compat=True,
        ),
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "seller": policy.seller_id}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/api/console/dashboard")
    async def console_dashboard() -> dict:
        stock = await store.get_stock(policy.sku)
        offers = await store.list_offers(limit=20)
        orders = await store.list_orders(limit=20)
        return {
            "seller_id": policy.seller_id,
            "pricing": {
                "product_name": policy.product_name,
                "sku": policy.sku,
                "currency": "USD",
                "list_unit_price_cents": policy.list_unit_price_cents,
                "base_warranty_months": policy.base_warranty_months,
                "warranty_addons_cents": policy.warranty_addons_cents,
                "returns_days": policy.returns_days,
                "delivery_days": policy.delivery_days,
                "rating": policy.rating,
                "sustainability_certified": policy.sustainability_certified,
            },
            "stock": {
                "on_hand": stock.on_hand,
                "incoming": stock.incoming,
                "incoming_days": stock.incoming_days,
            },
            "recent_offers": [
                {
                    "created_at": item["created_at"],
                    "offer": {
                        "offer_id": offer["offer_id"],
                        "status": offer["status"],
                        "currency": offer["currency"],
                        "total_cents": offer["total_cents"],
                        "line_items": [
                            {"quantity": line["quantity"], "name": line["name"]}
                            for line in offer["line_items"]
                        ],
                    },
                }
                for item in offers
                for offer in [item["offer"]]
            ],
            "recent_orders": [
                {
                    "created_at": item["created_at"],
                    "order": {
                        "order_id": order["order_id"],
                        "status": order["status"],
                        "currency": order["currency"],
                        "quantity": order["quantity"],
                        "total_cents": order["total_cents"],
                        "eta": order["eta"],
                        "fulfillment": {"status": order["fulfillment"]["status"]},
                    },
                }
                for item in orders
                for order in [item["order"]]
            ],
        }

    return app
