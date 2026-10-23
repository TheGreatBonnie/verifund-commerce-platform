from __future__ import annotations

import uvicorn

from orchestrator_agent.server import create_app
from orchestrator_agent.settings import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
