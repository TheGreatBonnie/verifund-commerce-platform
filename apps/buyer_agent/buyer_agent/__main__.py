import asyncio

import uvicorn
from commerce_core.checkpoints import open_checkpointer, prepare_checkpoint_storage

from buyer_agent.server import create_app
from buyer_agent.settings import Settings


async def main() -> None:
    settings = Settings()
    source = settings.checkpointer_source
    prepare_checkpoint_storage(source)
    async with open_checkpointer(source) as checkpointer:
        app = create_app(settings, checkpointer)
        config = uvicorn.Config(
            app, host=settings.host, port=settings.port, log_level="info"
        )
        await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
