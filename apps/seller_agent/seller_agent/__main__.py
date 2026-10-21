import uvicorn

from seller_agent.server import create_app
from seller_agent.settings import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
