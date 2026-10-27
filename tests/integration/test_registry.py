from pathlib import Path

import httpx
import pytest
import respx
from commerce_core.extension import EXTENSION_URI
from google.protobuf import json_format
from registry.api import create_app
from registry.settings import Settings

from tests.support.cards import build_test_card


@pytest.fixture
def seller_card_json() -> dict:
    return json_format.MessageToDict(
        build_test_card(), preserving_proto_field_name=False
    )


@pytest.fixture
async def registry_client(tmp_path: Path, seller_card_json: dict):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            "http://127.0.0.1:9201/.well-known/agent-card.json"
        ).mock(return_value=httpx.Response(200, json=seller_card_json))
        mock.get("http://127.0.0.1:9201/api/catalog").mock(
            return_value=httpx.Response(
                200,
                json={
                    "products": [
                        {
                            "sku": "NC-700-BLK",
                            "name": "Nimbus NC-700 ANC Headset",
                            "category": "consumer-electronics",
                        }
                    ]
                },
            )
        )
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}",
            admin_token="test-admin",
        )
        app = create_app(settings)
        await app.state.store.create_schema()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client
        await app.state.engine.dispose()


async def test_register_and_discover(registry_client, seller_card_json):
    create = await registry_client.post(
        "/v1/sellers",
        json={
            "card_url": "http://127.0.0.1:9201/.well-known/agent-card.json",
            "categories": ["consumer-electronics"],
        },
        headers={"Authorization": "Bearer test-admin"},
    )
    assert create.status_code == 201
    found = await registry_client.post(
        "/v1/discover",
        json={
            "category": "consumer-electronics",
            "required_extension": EXTENSION_URI,
        },
    )
    assert found.status_code == 200
    assert found.json()["sellers"][0]["seller_id"] == "northwind-audio"
    products = await registry_client.get("/v1/products")
    assert products.status_code == 200
    assert products.json()["products"][0]["seller_id"] == "northwind-audio"


async def test_registry_rejects_bad_admin_token(
    registry_client, seller_card_json
):
    response = await registry_client.post(
        "/v1/sellers",
        json={
            "card_url": "http://127.0.0.1:9201/.well-known/agent-card.json",
            "categories": ["consumer-electronics"],
        },
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


async def test_registry_rejects_non_local_card_url(registry_client):
    response = await registry_client.post(
        "/v1/sellers",
        json={
            "card_url": "http://example.com/card.json",
            "categories": ["consumer-electronics"],
        },
        headers={"Authorization": "Bearer test-admin"},
    )
    assert response.status_code == 400
