from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def configure_sqlite(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
