from sqlalchemy.ext.asyncio import AsyncEngine

from buyer_agent.trace import TraceStore


class BuyerStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.trace = TraceStore(engine)

    async def create_schema(self) -> None:
        await self.trace.create_schema()

    async def close(self) -> None:
        await self.engine.dispose()
