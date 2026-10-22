from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def build_buyer_agent_card(base_url: str) -> AgentCard:
    skills = [
        AgentSkill(
            id="commerce.sourcing",
            name="Source and negotiate",
            description="Discover sellers, negotiate offers, rank them, and prepare a human approval.",
            tags=["commerce", "sourcing", "negotiation"],
            input_modes=["application/json", "text/plain"],
            output_modes=["application/json", "text/plain"],
        ),
        AgentSkill(
            id="commerce.approval",
            name="Resume approved sourcing",
            description="Resume an interrupted sourcing run after a human approval decision.",
            tags=["commerce", "approval"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
    ]
    return AgentCard(
        name="MarketMesh Buyer",
        description="Commerce authority for MarketMesh sourcing runs.",
        version="1.0.0",
        provider=AgentProvider(organization="MarketMesh", url=base_url),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=skills,
    )
