from __future__ import annotations

import uvicorn

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings


def main() -> None:
    settings = Settings()
    settings.validate_for_mode()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        workers=1,
    )


if __name__ == "__main__":
    main()
