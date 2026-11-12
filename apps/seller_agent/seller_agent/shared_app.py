from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from commerce_core.checkpoints import open_checkpointer, prepare_checkpoint_storage
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from starlette.routing import Route

from seller_agent.card import build_agent_card
from seller_agent.internal_routes import router as internal_router
from seller_agent.planner import select_seller_planner
from seller_agent.service import SellerService
from seller_agent.settings import Settings
from seller_agent.settlement import SellerSettlementClient
from seller_agent.shared_auth import (
    A2A_CALL_PURPOSE,
    ControlPlaneCredentialVerifier,
    SharedAuthMiddleware,
    SharedCallContextBuilder,
    StaticDemoCredentialVerifier,
)
from seller_agent.shared_review_store import OrgScopedAgreementReviewStore
from seller_agent.shared_runtime import (
    TenantContext,
    TenantResolver,
    TenantRoutingExecutor,
)
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from seller_agent.shared_store import ConfigSnapshot, OrgScopedStore, _snapshot
from seller_agent.shared_sweeper import SharedEvidenceSweeper


class _CallableVerifier:
    def __init__(self, verify) -> None:
        self._verify = verify

    async def verify(self, token: str,
                     purpose: str = A2A_CALL_PURPOSE) -> dict[str, Any] | None:
        return await self._verify(token, purpose=purpose)


def _verifier_for(settings: Settings, verifier: Any | None):
    if verifier is not None:
        if hasattr(verifier, "verify"):
            return verifier
        return _CallableVerifier(verifier)
    if settings.verifund_mode == "off":
        return StaticDemoCredentialVerifier(settings.demo_credentials_path)
    return ControlPlaneCredentialVerifier(
        settings.verifund_url,
        ttl_seconds=settings.credential_cache_ttl_seconds,
    )


class SharedRuntime:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        *,
        graph,
        settlement: SellerSettlementClient | None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.graph = graph
        self.settlement = settlement
        self.planner = select_seller_planner(
            settings.llm_mode,
            settings.nebius_api_key,
            settings.nebius_base_url,
            settings.nebius_model,
        )

    async def service_for(self, tenant: TenantContext) -> SellerService:
        store = OrgScopedStore(
            self.engine,
            organization_id=tenant.organization_id,
            agent_id=tenant.agent_id,
        )
        policy = await store.load_policy()
        return SellerService(
            store=store,
            policy=policy,
            planner=self.planner,
            mandate=await store.load_mandate(),
            settlement=self.settlement,
            settlement_enabled=self.settlement is not None,
            evidence_outbox=None,
            auto_evidence=self.settings.verifund_auto_evidence,
            review_store=OrgScopedAgreementReviewStore(
                self.engine, tenant.organization_id),
            graph=self.graph,
            scope=f"organization_id:{tenant.organization_id}:{tenant.agent_id}",
            organization_id=tenant.organization_id,
        )


async def _active_config(engine: AsyncEngine,
                         seller_id: str) -> ConfigSnapshot | None:
    async with engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT * FROM seller_configs "
                 "WHERE seller_id = :s AND status = 'active'"),
            {"s": seller_id},
        )).first()
    return _snapshot(row) if row else None


def _require_internal(request: Request) -> None:
    settings = request.app.state.settings
    token = request.headers.get("x-internal-token", "")
    if not settings.internal_api_token or not hmac.compare_digest(
        token, settings.internal_api_token
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "internal_auth",
                    "message": "bad internal credential"},
        )


def _generic_card(settings: Settings) -> AgentCard:
    return AgentCard(
        name="MarketMesh Seller Network",
        description="Multi-tenant MarketMesh seller agents.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=f"{settings.public_base_url}/a2a",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json"],
    )


async def _catalog(policy, store: OrgScopedStore) -> dict:
    items = []
    for product in policy.catalog():
        stock = await store.get_stock(product.sku)
        items.append({
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "image_url": product.image_url,
            "list_unit_price_cents": product.list_unit_price_cents,
            "original_unit_price_cents": product.original_unit_price_cents,
            "base_warranty_months": product.base_warranty_months,
            "returns_days": product.returns_days,
            "delivery_days": product.delivery_days,
            "sustainability_certified": product.sustainability_certified,
            "rating": product.rating,
            "reviews": product.reviews,
            "tag": product.tag,
            "seller_id": policy.seller_id,
            "seller_name": policy.name,
            "currency": "USD",
            "on_hand": stock.on_hand,
            "incoming": stock.incoming,
            "incoming_days": stock.incoming_days,
        })
    return {
        "seller_id": policy.seller_id,
        "seller_name": policy.name,
        "products": items,
    }


async def _dashboard(policy, store: OrgScopedStore,
                     service: SellerService) -> dict:
    catalog = policy.catalog()
    product_rows = []
    for product in catalog:
        stock = await store.get_stock(product.sku)
        product_rows.append({
            "sku": product.sku,
            "product_name": product.name,
            "category": product.category,
            "description": product.description,
            "list_unit_price_cents": product.list_unit_price_cents,
            "currency": "USD",
            "stock": {
                "on_hand": stock.on_hand,
                "incoming": stock.incoming,
                "incoming_days": stock.incoming_days,
            },
        })
    featured = catalog[0]
    stock = await store.get_stock(featured.sku)
    offers = await store.list_offers(limit=20)
    orders = await store.list_orders(limit=20)
    return {
        "seller_id": policy.seller_id,
        "pricing": {
            "product_name": featured.name,
            "sku": featured.sku,
            "currency": "USD",
            "list_unit_price_cents": featured.list_unit_price_cents,
            "base_warranty_months": featured.base_warranty_months,
            "warranty_addons_cents": featured.warranty_addons_cents,
            "returns_days": featured.returns_days,
            "delivery_days": featured.delivery_days,
            "rating": featured.rating,
            "sustainability_certified": featured.sustainability_certified,
        },
        "products": product_rows,
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
        "settlement": await service.settlement_status(),
    }


def create_shared_app(
    settings: Settings, *, credential_verifier: Any | None = None
) -> FastAPI:
    verifier = _verifier_for(settings, credential_verifier)
    engine = create_async_engine(settings.shared_db_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await configure_shared_engine(engine)
        await create_shared_schema(engine)
        app.state.shared_engine = engine
        app.state.engine = engine
        app.state.settings = settings
        app.state.credential_verifier = verifier

        checkpoint_source = settings.checkpointer_source
        prepare_checkpoint_storage(checkpoint_source)
        settlement = None
        if settings.verifund_mode != "off":
            settlement = SellerSettlementClient(
                settings.verifund_url,
                internal_token=settings.internal_api_token,
                timeout_seconds=settings.verifund_timeout_seconds,
            )

        async with open_checkpointer(checkpoint_source) as checkpointer:

            def owner_resolver(context) -> str:
                caller = (context.state or {}).get("caller") or {}
                return caller.get("organization_id") or ""

            task_store = DatabaseTaskStore(
                engine=engine,
                create_table=True,
                owner_resolver=owner_resolver,
            )
            from seller_agent.graph import build_graph
            graph = build_graph(checkpointer=checkpointer)
            runtime = SharedRuntime(
                engine, settings, graph=graph, settlement=settlement)
            resolver = TenantResolver(engine)
            handler = DefaultRequestHandler(
                agent_executor=TenantRoutingExecutor(resolver, runtime),
                task_store=task_store,
                agent_card=_generic_card(settings),
            )
            dispatcher = JsonRpcDispatcher(
                handler,
                context_builder=SharedCallContextBuilder(),
                enable_v0_3_compat=True,
            )
            app.state.handler = handler
            app.state.dispatcher = dispatcher
            app.state.shared_runtime = runtime

            sweeper = None
            if settlement is not None:
                sweeper = SharedEvidenceSweeper(
                    engine,
                    settlement,
                    interval_seconds=settings.evidence_sweep_seconds,
                    retry_seconds=settings.verifund_evidence_retry_seconds,
                )
                await sweeper.start()
            try:
                yield
            finally:
                if sweeper is not None:
                    await sweeper.stop()
                if settlement is not None:
                    await settlement.close()
        await engine.dispose()

    app = FastAPI(title="seller-shared", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(SharedAuthMiddleware, verifier=verifier)
    app.include_router(internal_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/{seller_id}/.well-known/agent-card.json")
    async def card(seller_id: str) -> JSONResponse:
        snapshot = await _active_config(engine, seller_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="unknown seller")
        store = OrgScopedStore(
            engine,
            organization_id=snapshot.organization_id,
            agent_id=snapshot.agent_id,
        )
        policy = await store.load_policy()
        card_value = build_agent_card(
            policy,
            f"{settings.public_base_url}/{seller_id}",
            tenant=snapshot.agent_id,
        )
        return JSONResponse(MessageToDict(card_value))

    @app.get("/{seller_id}/api/catalog")
    async def public_catalog(seller_id: str) -> dict:
        snapshot = await _active_config(engine, seller_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="unknown seller")
        store = OrgScopedStore(
            engine,
            organization_id=snapshot.organization_id,
            agent_id=snapshot.agent_id,
        )
        return await _catalog(await store.load_policy(), store)

    @app.get("/{seller_id}/api/console/dashboard")
    async def console_dashboard(seller_id: str, request: Request) -> dict:
        _require_internal(request)
        snapshot = await _active_config(engine, seller_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="unknown seller")
        tenant = TenantContext(
            agent_id=snapshot.agent_id,
            organization_id=snapshot.organization_id,
            seller_id=snapshot.seller_id,
            config=snapshot,
        )
        service = await request.app.state.shared_runtime.service_for(tenant)
        return await _dashboard(service.policy, service.store, service)

    async def dispatch(request: Request):
        return await request.app.state.dispatcher.handle_requests(request)

    app.router.routes.append(Route(
        "/{seller_id}/a2a", dispatch, methods=["POST"]))
    app.router.routes.append(Route("/a2a", dispatch, methods=["POST"]))

    return app
