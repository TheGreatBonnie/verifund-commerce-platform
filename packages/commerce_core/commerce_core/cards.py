from typing import Any

import httpx
from a2a.types.a2a_pb2 import AgentCard
from google.protobuf import json_format

from commerce_core.extension import EXTENSION_URI

REQUIRED_SKILLS = {
    "commerce.catalog.search",
    "commerce.quote",
    "commerce.negotiate",
    "commerce.order",
}


def parse_agent_card(data: dict[str, Any]) -> AgentCard:
    card = AgentCard()
    json_format.ParseDict(data, card)
    return card


def validate_agent_card(card: AgentCard) -> list[str]:
    errors: list[str] = []
    if not card.name:
        errors.append("missing name")
    if not card.version:
        errors.append("missing version")
    interfaces = list(card.supported_interfaces)
    if not any(
        i.protocol_binding == "JSONRPC" and i.protocol_version.startswith("1.")
        for i in interfaces
    ):
        errors.append("missing JSONRPC A2A 1.x interface")
    if not card.capabilities.streaming:
        errors.append("streaming is required")
    extensions = {e.uri: e for e in card.capabilities.extensions}
    if EXTENSION_URI not in extensions or not extensions[EXTENSION_URI].required:
        errors.append("required commerce extension missing")
    else:
        params = json_format.MessageToDict(extensions[EXTENSION_URI].params)
        rating = params.get("rating")
        if not isinstance(rating, (int, float)) or not 0 <= rating <= 5:
            errors.append("commerce extension requires rating in [0,5]")
        if not isinstance(params.get("sustainability_certified"), bool):
            errors.append("commerce extension requires sustainability_certified")
    skill_ids = {s.id for s in card.skills}
    if not REQUIRED_SKILLS.issubset(skill_ids):
        errors.append(f"missing skills: {sorted(REQUIRED_SKILLS - skill_ids)}")
    if "bearer" not in card.security_schemes:
        errors.append("missing bearer security scheme")
    return errors


def card_commerce_metadata(card: AgentCard) -> dict[str, Any]:
    for extension in card.capabilities.extensions:
        if extension.uri == EXTENSION_URI:
            return json_format.MessageToDict(extension.params)
    raise ValueError("commerce extension metadata is missing")


DEFAULT_CARD_HOSTS = (
    "127.0.0.1",
    "localhost",
    "northwind",
    "circuitforge",
    "aurora",
)


async def fetch_agent_card(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    allowed_hosts: tuple[str, ...] = DEFAULT_CARD_HOSTS,
) -> AgentCard:
    parsed = httpx.URL(url)
    if parsed.scheme != "http" or parsed.host not in allowed_hosts:
        raise ValueError("prototype card fetch is restricted to allowed local hosts")
    if client is None:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(url)
    else:
        response = await client.get(url)
    response.raise_for_status()
    return parse_agent_card(response.json())
