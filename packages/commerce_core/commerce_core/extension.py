from typing import Any

from pydantic import BaseModel, ConfigDict, Field

EXTENSION_URI = "https://marketmesh.example/extensions/commerce/v1"
SCHEMA_BASE = f"{EXTENSION_URI}/schemas"
SCHEMA_FILES = {
    "rfq": "rfq.json",
    "offer": "offer.json",
    "counter_offer": "counter-offer.json",
    "accept_offer": "accept-offer.json",
    "purchase_order": "purchase-order.json",
    "order": "order.json",
    "commerce_error": "commerce-error.json",
}

class CommerceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_uri: str = Field(alias="schema")
    schema_version: str = "1.0"
    payload: dict[str, Any]


def expected_schema(kind: str) -> str:
    try:
        return f"{SCHEMA_BASE}/{SCHEMA_FILES[kind]}"
    except KeyError as exc:
        raise ValueError(f"unknown commerce payload kind: {kind}") from exc


def wrap_payload(kind: str, payload: BaseModel) -> dict[str, Any]:
    return {
        "schema": expected_schema(kind),
        "schema_version": "1.0",
        "payload": payload.model_dump(mode="json"),
    }


def unwrap_payload(kind: str, envelope: dict[str, Any]) -> dict[str, Any]:
    parsed = CommerceEnvelope.model_validate(envelope)
    if parsed.schema_uri != expected_schema(kind):
        raise ValueError(f"unexpected schema for {kind}: {parsed.schema_uri}")
    if parsed.schema_version != "1.0":
        raise ValueError(f"unsupported schema version: {parsed.schema_version}")
    return parsed.payload


def parse_payload[ModelT: BaseModel](
    kind: str, envelope: dict[str, Any], model: type[ModelT]
) -> ModelT:
    return model.model_validate(unwrap_payload(kind, envelope))
