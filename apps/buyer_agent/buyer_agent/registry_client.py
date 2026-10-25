from __future__ import annotations

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


class RegistryClient:
    def __init__(
        self,
        *,
        registry_url: str,
        allowed_card_hosts: tuple[str, ...],
        seller_tokens: dict[str, str],
        trace: TraceStore | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.registry_url = registry_url.rstrip("/")
        self.allowed_card_hosts = allowed_card_hosts
        self.seller_tokens = seller_tokens
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

    async def discover(self, category: str) -> list[SellerEndpoint]:
        response = await self.http.post(
            f"{self.registry_url}/v1/discover",
            json={
                "category": category,
                "required_extension": EXTENSION_URI,
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

    async def fetch_seller_dashboard(self, seller_id: str) -> dict[str, Any]:
        response = await self.http.get(
            f"{self.registry_url}/v1/sellers/{quote(seller_id, safe='')}"
        )
        if response.status_code == 404:
            raise LookupError(f"seller {seller_id!r} is not registered")
        response.raise_for_status()
        seller = response.json()
        token = self.seller_tokens.get(seller_id)
        if not token:
            raise RuntimeError(f"missing buyer credential for seller {seller_id}")

        card = await fetch_agent_card(
            seller["card_url"],
            client=self.http,
            allowed_hosts=self.allowed_card_hosts,
        )
        errors = validate_agent_card(card)
        if errors:
            raise RuntimeError("seller Agent Card is invalid: " + "; ".join(errors))

        dashboard_url = str(
            httpx.URL(seller["card_url"]).copy_with(
                path="/api/console/dashboard", query=None, fragment=None
            )
        )
        dashboard = await self.http.get(
            dashboard_url,
            headers={"Authorization": f"Bearer {token}"},
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
