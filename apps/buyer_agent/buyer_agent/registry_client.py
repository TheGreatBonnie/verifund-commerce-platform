from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from commerce_core.cards import (
    card_commerce_metadata,
    fetch_agent_card,
    validate_agent_card,
)
from commerce_core.extension import EXTENSION_URI

from buyer_agent.trace import TraceStore


@dataclass
class SellerEndpoint:
    seller_id: str
    name: str
    card_url: str
    card: Any
    token: str
    rating: float
    sustainability_certified: bool


def seller_path_base(card_url: str) -> str:
    url = httpx.URL(card_url)
    suffix = "/.well-known/agent-card.json"
    path = url.path
    path = path.removesuffix(suffix)
    return str(url.copy_with(path=path or "/", query=None, fragment=None)).rstrip("/")


def seller_catalog_url(card_url: str) -> str:
    return f"{seller_path_base(card_url)}/api/catalog"


def seller_dashboard_url(card_url: str) -> str:
    return f"{seller_path_base(card_url)}/api/console/dashboard"


class RegistryClient:
    def __init__(
        self,
        *,
        registry_url: str,
        allowed_card_hosts: tuple[str, ...],
        seller_tokens: dict[str, str],
        seller_internal_token: str = "",
        trace: TraceStore | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.registry_url = registry_url.rstrip("/")
        self.allowed_card_hosts = allowed_card_hosts
        self.seller_tokens = seller_tokens
        self.seller_internal_token = seller_internal_token
        self.trace = trace
        self.http = client or httpx.AsyncClient(timeout=10.0)
        self.fetch_calls = 0
        self._endpoints: dict[str, SellerEndpoint] = {}

    async def close(self) -> None:
        await self.http.aclose()

    def endpoint(self, seller_id: str) -> SellerEndpoint:
        try:
            return self._endpoints[seller_id]
        except KeyError:
            raise KeyError(
                f"seller {seller_id!r} was not discovered or failed validation"
            ) from None

    async def poll_registry(self) -> dict[str, SellerEndpoint]:
        """Fetch GET /v1/sellers, validate cards, atomically swap _endpoints.

        On registry failure (HTTP error, bad JSON) keep the last known map.
        """
        import logging
        try:
            response = await self.http.get(f"{self.registry_url}/v1/sellers")
            response.raise_for_status()
            entries = response.json().get("sellers", [])
        except (httpx.HTTPError, ValueError) as exc:
            logging.getLogger(__name__).warning("registry poll failed: %s", exc)
            return self._endpoints
        new_endpoints: dict[str, SellerEndpoint] = {}
        for entry in entries:
            seller_id, card_url = entry["seller_id"], entry["card_url"]
            self.fetch_calls += 1
            try:
                card = await fetch_agent_card(card_url, client=self.http, allowed_hosts=self.allowed_card_hosts)
            except Exception as exc:  # noqa: BLE001
                await self._trace_invalid(entry, str(exc))
                continue
            if validate_agent_card(card):
                continue
            token = self.seller_tokens.get(seller_id)
            if not token:
                continue
            metadata = card_commerce_metadata(card)
            new_endpoints[seller_id] = SellerEndpoint(
                seller_id=seller_id, name=card.name, card_url=card_url, card=card,
                token=token, rating=float(metadata["rating"]),
                sustainability_certified=bool(metadata["sustainability_certified"]),
            )
        self._endpoints = new_endpoints
        return self._endpoints

    async def discover(
        self, category: str, product_sku: str | None = None
    ) -> list[SellerEndpoint]:
        response = await self.http.post(
            f"{self.registry_url}/v1/discover",
            json={
                "category": category,
                "required_extension": EXTENSION_URI,
                "product_sku": product_sku,
            },
        )
        response.raise_for_status()
        endpoints: list[SellerEndpoint] = []
        for result in response.json().get("sellers", []):
            seller_id = result["seller_id"]
            card_url = result["card_url"]
            self.fetch_calls += 1
            try:
                card = await fetch_agent_card(
                    card_url,
                    client=self.http,
                    allowed_hosts=self.allowed_card_hosts,
                )
            except Exception as exc:  # noqa: BLE001
                await self._trace_invalid(result, str(exc))
                continue
            errors = validate_agent_card(card)
            if errors:
                await self._trace_invalid(result, "; ".join(errors))
                continue
            token = self.seller_tokens.get(seller_id)
            if not token:
                raise ValueError(
                    f"missing buyer credential for seller {seller_id}"
                )
            metadata = card_commerce_metadata(card)
            endpoint = SellerEndpoint(
                seller_id=seller_id,
                name=card.name,
                card_url=card_url,
                card=card,
                token=token,
                rating=float(metadata["rating"]),
                sustainability_certified=bool(
                    metadata["sustainability_certified"]
                ),
            )
            self._endpoints[seller_id] = endpoint
            endpoints.append(endpoint)
        return endpoints

    async def marketplace_products(
        self, *, category: str | None = None, query: str | None = None
    ) -> list[dict[str, Any]]:
        response = await self.http.get(
            f"{self.registry_url}/v1/products",
            params={key: value for key, value in {"category": category, "q": query}.items() if value},
        )
        response.raise_for_status()
        listings = response.json().get("products", [])
        grouped: dict[str, dict[str, Any]] = {}
        for listing in listings:
            sku = listing["sku"]
            product = grouped.setdefault(
                sku,
                {
                    "id": sku,
                    "sku": sku,
                    "name": listing["name"],
                    "category": listing["category"],
                    "description": listing.get("description", ""),
                    "image_emoji": listing.get("image_emoji", "📦"),
                    "color": listing.get("color", "#eef2ed"),
                    "original_unit_price_cents": listing.get("original_unit_price_cents"),
                    "rating": listing.get("rating", 0),
                    "reviews": listing.get("reviews", ""),
                    "tag": listing.get("tag", "Available"),
                    "offers": [],
                },
            )
            product["offers"].append(
                {
                    "seller_id": listing["seller_id"],
                    "seller_name": listing["seller_name"],
                    "unit_price_cents": listing["list_unit_price_cents"],
                    "currency": "USD",
                    "available": False,
                    "on_hand": 0,
                    "incoming": 0,
                }
            )

        async def refresh_seller_catalog(seller_id: str, card_url: str) -> None:
            catalog_url = seller_catalog_url(card_url)
            try:
                live = await self.http.get(catalog_url)
                live.raise_for_status()
                live_products = {
                    product["sku"]: product
                    for product in live.json().get("products", [])
                }
                for sku, product in grouped.items():
                    item = live_products.get(sku)
                    if item is None:
                        continue
                    offer = next(
                        (entry for entry in product["offers"] if entry["seller_id"] == seller_id),
                        None,
                    )
                    if offer is None:
                        continue
                    offer["available"] = item["on_hand"] > 0 or item["incoming"] > 0
                    offer["on_hand"] = item["on_hand"]
                    offer["incoming"] = item["incoming"]
            except (httpx.HTTPError, KeyError, ValueError):
                return

        seller_urls = {
            listing["seller_id"]: listing["card_url"] for listing in listings
        }
        await asyncio.gather(
            *(
                refresh_seller_catalog(seller_id, card_url)
                for seller_id, card_url in seller_urls.items()
            )
        )
        result = list(grouped.values())
        for product in result:
            product["offers"].sort(
                key=lambda offer: (not offer["available"], offer["unit_price_cents"])
            )
            product["unit_price_cents"] = product["offers"][0]["unit_price_cents"]
            product["seller"] = product["offers"][0]["seller_name"]
        return result

    async def fetch_seller_dashboard(self, seller_id: str) -> dict[str, Any]:
        response = await self.http.get(
            f"{self.registry_url}/v1/sellers/{quote(seller_id, safe='')}"
        )
        if response.status_code == 404:
            raise LookupError(f"seller {seller_id!r} is not registered")
        response.raise_for_status()
        seller = response.json()
        if not self.seller_internal_token:
            raise RuntimeError(f"missing seller internal token for {seller_id}")

        card = await fetch_agent_card(
            seller["card_url"],
            client=self.http,
            allowed_hosts=self.allowed_card_hosts,
        )
        errors = validate_agent_card(card)
        if errors:
            raise RuntimeError("seller Agent Card is invalid: " + "; ".join(errors))

        dashboard_url = seller_dashboard_url(seller["card_url"])
        dashboard = await self.http.get(
            dashboard_url,
            headers={"X-Internal-Token": self.seller_internal_token},
        )
        dashboard.raise_for_status()
        return dashboard.json()

    async def _trace_invalid(
        self, result: dict[str, Any], reason: str
    ) -> None:
        if self.trace is None:
            return
        await self.trace.record(
            "discovery",
            direction="internal",
            method="ValidateAgentCard",
            seller_id=result.get("seller_id"),
            payload={"card_url": result.get("card_url"), "error": reason},
        )
