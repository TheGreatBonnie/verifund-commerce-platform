from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from a2a.client.client import Client
from a2a.types.a2a_pb2 import AgentCard


@dataclass
class SellerSession:
    client: Client
    card: AgentCard
    store: Any
    base_url: str

    def __iter__(self):
        yield self.client
        yield self.card
