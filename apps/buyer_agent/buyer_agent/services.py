from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from buyer_agent.a2a_client import SellerA2AClient
from buyer_agent.agreement_service import BuyerAgreementService
from buyer_agent.registry_client import RegistryClient
from buyer_agent.settings import Settings
from buyer_agent.settlement import SettlementCoordinator
from buyer_agent.settlement_client import BuyerSettlementClient
from buyer_agent.store import BuyerStore


class BuyerServicesLike(Protocol):
    """Service surface required to build the buyer app.

    Production passes `BuyerServices`; tests inject duck-typed doubles.
    """

    @property
    def registry(self) -> Any: ...

    @property
    def a2a(self) -> Any: ...

    @property
    def trace(self) -> Any: ...


@dataclass
class BuyerServices:
    settings: Settings
    engine: AsyncEngine
    store: BuyerStore
    registry: RegistryClient
    a2a: SellerA2AClient
    settlement: BuyerSettlementClient | None = None
    coordinator: SettlementCoordinator | None = None
    agreements: BuyerAgreementService | None = None

    @property
    def trace(self):
        return self.store.trace

    async def close(self) -> None:
        if self.settlement is not None:
            await self.settlement.close()
        await self.registry.close()
        await self.engine.dispose()


def build_services(settings: Settings, engine: AsyncEngine) -> BuyerServices:
    store = BuyerStore(engine)
    registry = RegistryClient(
        registry_url=settings.registry_url,
        allowed_card_hosts=settings.allowed_card_hosts,
        control_plane_url=getattr(settings, "verifund_url", ""),
        buyer_internal_token=getattr(settings, "buyer_internal_token", ""),
        seller_internal_token=getattr(settings, "seller_internal_token", ""),
        trace=store.trace,
    )
    coordinator = SettlementCoordinator()
    settlement = None
    agreements = None
    if settings.verifund_mode != "off":
        settlement = BuyerSettlementClient(
            settings.verifund_url,
            ops_token=settings.verifund_ops_token,
            timeout_seconds=settings.verifund_timeout_seconds,
            buyer_settlement_internal_token=getattr(
                settings, "buyer_settlement_internal_token", None
            ),
            buyer_clerk_user_id=getattr(settings, "buyer_clerk_user_id", "user_buyer"),
        )
        agreements = BuyerAgreementService(
            client=settlement,
            store=store.settlement,
            console_base_url=settings.console_base_url,
        )
    return BuyerServices(
        settings=settings,
        engine=engine,
        store=store,
        registry=registry,
        a2a=SellerA2AClient(store.trace),
        settlement=settlement,
        coordinator=coordinator,
        agreements=agreements,
    )
