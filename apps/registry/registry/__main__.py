import uvicorn

from registry.api import create_app
from registry.settings import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
