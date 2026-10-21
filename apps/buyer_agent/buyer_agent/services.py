from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from buyer_agent.a2a_client import SellerA2AClient
from buyer_agent.registry_client import RegistryClient
from buyer_agent.settings import Settings
from buyer_agent.store import BuyerStore


@dataclass
class BuyerServices:
    settings: Settings
    engine: AsyncEngine
    store: BuyerStore
    registry: RegistryClient
    a2a: SellerA2AClient

    @property
    def trace(self):
        return self.store.trace

    async def close(self) -> None:
        await self.registry.close()
        await self.engine.dispose()


def build_services(settings: Settings, engine: AsyncEngine) -> BuyerServices:
    store = BuyerStore(engine)
    registry = RegistryClient(
        registry_url=settings.registry_url,
        allowed_card_hosts=settings.allowed_card_hosts,
        seller_tokens=settings.seller_tokens,
        trace=store.trace,
    )
    return BuyerServices(
        settings=settings,
        engine=engine,
        store=store,
        registry=registry,
        a2a=SellerA2AClient(store.trace),
    )
