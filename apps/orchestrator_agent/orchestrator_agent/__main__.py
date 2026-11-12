from pathlib import Path

import uvicorn
from commerce_core.db import sqlite_file_path

from orchestrator_agent.server import create_app
from orchestrator_agent.settings import Settings


def main() -> None:
    settings = Settings()
    db_path = sqlite_file_path(settings.session_db_url)
    if db_path is not None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
