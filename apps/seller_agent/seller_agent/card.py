from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from commerce_core.extension import EXTENSION_URI
from commerce_core.pricing import SellerPolicy


def build_agent_card(policy: SellerPolicy, base_url: str) -> AgentCard:
    skills = [
        AgentSkill(
            id="commerce.catalog.search",
            name="Search catalog",
            description="Find products by category and query.",
            tags=["commerce", "catalog"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
        AgentSkill(
            id="commerce.quote",
            name="Quote an item",
            description="Return a structured initial quote.",
            tags=["commerce", "quote"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
        AgentSkill(
            id="commerce.negotiate",
            name="Negotiate an offer",
            description="Counter or accept structured offers.",
            tags=["commerce", "negotiation"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
        AgentSkill(
            id="commerce.order",
            name="Place an order",
            description="Reserve stock and create an idempotent order.",
            tags=["commerce", "order"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
        AgentSkill(
            id="commerce.agreement.review",
            name="Review a Verifund agreement",
            description="Validate a Verifund agreement against the stored offer.",
            tags=["verifund", "agreement"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
    ]
    return AgentCard(
        name=policy.name,
        description=policy.tagline,
        version="1.0.0",
        provider=AgentProvider(organization=policy.name, url=base_url),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
            extensions=[
                AgentExtension(
                    uri=EXTENSION_URI,
                    description="MarketMesh commerce extension v1",
                    required=True,
                    params={
                        "rating": policy.rating,
                        "sustainability_certified": policy.sustainability_certified,
                    },
                )
            ],
        ),
        security_schemes={
            "bearer": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="bearer", bearer_format="opaque"
                )
            )
        },
        security_requirements=[
            SecurityRequirement(schemes={"bearer": StringList()})
        ],
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json"],
        skills=skills,
    )
