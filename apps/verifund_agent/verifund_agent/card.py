from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol

SKILLS = (
    ("verifund.agreement.create", "Create agreement", "Start the lifecycle: assemble the agreement from the exact Buyer award and return the first checkpoint."),
    ("verifund.transaction.status", "Transaction status", "Poll the durable lifecycle task and return its current checkpoint or projection."),
    ("verifund.transaction.fund", "Fund transaction", "Resume the funding checkpoint with the structured human decision and return the checkout handoff."),
    ("verifund.evidence.review", "Review evidence", "Advance the purchase-order and evidence checkpoints and return verification status."),
    ("verifund.transaction.release", "Release transaction", "Resume the release checkpoint with the structured human decision."),
    ("verifund.receipt.get", "Get receipt", "Return the verified signed receipt after release."),
)


def build_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Verifund",
        description="Agreement and settlement control for MarketMesh.",
        version="1.0.0",
        provider=AgentProvider(organization="MarketMesh", url=base_url),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url.rstrip('/')}/a2a",
                protocol_binding=TransportProtocol.JSONRPC,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id=skill_id,
                name=name,
                description=description,
                tags=["verifund", "settlement"],
                input_modes=["application/json"],
                output_modes=["application/json"],
            )
            for skill_id, name, description in SKILLS
        ],
        security_schemes={
            "bearer": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer")
            )
        },
        security_requirements=[
            SecurityRequirement(schemes={"bearer": StringList(list=[])})
        ],
    )
