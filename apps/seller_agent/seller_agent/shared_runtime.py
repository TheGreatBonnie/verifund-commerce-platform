from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from seller_agent.shared_store import ConfigSnapshot, _snapshot


class UnknownTenant(Exception):
    """The requested seller agent does not exist or is not active."""


class TenantForbidden(Exception):
    """The tenant and the request path disagree about the recipient."""


@dataclass(frozen=True)
class TenantContext:
    agent_id: str
    organization_id: str
    seller_id: str
    config: ConfigSnapshot


class SellerRuntime(Protocol):
    async def service_for(self, tenant: TenantContext): ...


class TenantResolver:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def resolve(
        self, tenant: str, path_seller_id: str | None = None
    ) -> TenantContext:
        agent_id = (tenant or "").strip()
        if not agent_id:
            if not path_seller_id:
                raise UnknownTenant("tenant is required")
            agent_id = f"agent_{path_seller_id}"
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT * FROM seller_configs WHERE agent_id = :a"),
                {"a": agent_id},
            )).first()
        if row is None or row.status != "active":
            raise UnknownTenant(agent_id)
        if path_seller_id and row.seller_id != path_seller_id:
            raise TenantForbidden(
                f"path {path_seller_id!r} does not match tenant seller "
                f"{row.seller_id!r}"
            )
        return TenantContext(
            agent_id=row.agent_id,
            organization_id=row.organization_id,
            seller_id=row.seller_id,
            config=_snapshot(row),
        )


class TenantRoutingExecutor(AgentExecutor):
    """Resolve the recipient per request, then run the seller executor."""

    def __init__(self, resolver: TenantResolver, runtime: SellerRuntime) -> None:
        self.resolver = resolver
        self.runtime = runtime

    async def _service(self, context: RequestContext):
        state: MutableMapping[str, Any] = context.call_context.state
        try:
            seller = await self.resolver.resolve(
                context.tenant,
                path_seller_id=state.get("seller_id") or None,
            )
        except UnknownTenant as exc:
            raise TaskNotFoundError(
                f"unknown seller agent: {exc}") from exc
        except TenantForbidden as exc:
            raise InvalidParamsError(str(exc)) from exc

        caller = state.get("caller") or {}
        if caller.get("organization_id") == seller.organization_id:
            raise InvalidParamsError(
                "caller and recipient organizations must differ")

        service = await self.runtime.service_for(seller)
        return seller, service

    async def execute(self, context: RequestContext,
                      event_queue: EventQueue) -> None:
        from seller_agent.executor import SellerExecutor

        _seller, service = await self._service(context)
        await service.store.record_task_ownership(
            context.task_id or "", context.context_id)
        await SellerExecutor(service).execute(context, event_queue)

    async def cancel(self, context: RequestContext,
                     event_queue: EventQueue) -> None:
        from seller_agent.executor import SellerExecutor

        _, service = await self._service(context)
        await SellerExecutor(service).cancel(context, event_queue)
