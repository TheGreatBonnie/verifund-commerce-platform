from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from buyer_agent.server import create_app as create_buyer
from buyer_agent.settings import Settings as BuyerSettings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from orchestrator_agent.server import create_app as create_orchestrator
from orchestrator_agent.settings import Settings as OrchestratorSettings
from registry.api import create_app as create_registry
from registry.settings import Settings as RegistrySettings
from seller_agent.server import create_app as create_seller
from seller_agent.settings import Settings as SellerSettings
from verifund_agent.server import create_app as create_verifund_agent
from verifund_agent.settings import Settings as VerifundAgentSettings
from verifund_control_plane.app import create_app as create_control_plane
from verifund_control_plane.settings import Settings as ControlPlaneSettings

from gateway.app import build_app
from gateway.settings import Settings


@asynccontextmanager
async def gateway_stack():
    """Assemble all six service apps and keep their checkpointers alive.

    Yields the mounted gateway FastAPI app. The buyer and verifund-agent
    SQLite checkpointers must outlive the server, so they are opened here.
    """
    buyer_settings = BuyerSettings()
    agent_settings = VerifundAgentSettings()
    orchestrator_settings = OrchestratorSettings()
    control_plane_settings = ControlPlaneSettings()
    control_plane_settings.validate_for_mode()

    Path(buyer_settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    Path(agent_settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    session_db = orchestrator_settings.session_db_url.split("///", 1)[-1]
    Path(session_db).parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(
        str(buyer_settings.checkpoint_path)
    ) as buyer_checkpointer, AsyncSqliteSaver.from_conn_string(
        str(agent_settings.checkpoint_path)
    ) as agent_checkpointer:
        sub_apps = {
            "orchestrator": create_orchestrator(orchestrator_settings),
            "buyer": create_buyer(buyer_settings, buyer_checkpointer),
            "registry": create_registry(RegistrySettings()),
            "seller": create_seller(SellerSettings()),
            "control_plane": create_control_plane(control_plane_settings),
            "verifund_agent": create_verifund_agent(
                agent_settings, agent_checkpointer
            ),
        }
        yield build_app(sub_apps)


async def main() -> None:
    settings = Settings()
    async with gateway_stack() as app:
        config = uvicorn.Config(
            app, host=settings.host, port=settings.port, log_level="info"
        )
        await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
