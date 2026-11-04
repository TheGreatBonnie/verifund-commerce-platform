import asyncio
from pathlib import Path

import uvicorn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from verifund_agent.server import create_app
from verifund_agent.settings import Settings


async def main() -> None:
    settings = Settings()
    Path(settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(
        str(settings.checkpoint_path)
    ) as checkpointer:
        app = create_app(settings, checkpointer)
        config = uvicorn.Config(
            app, host=settings.host, port=settings.agent_port, log_level="info"
        )
        await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
