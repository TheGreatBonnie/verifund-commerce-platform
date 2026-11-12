"""Object storage adapter (plan Task 21)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


@dataclass
class StoredObject:
    key: str
    data: bytes
    content_type: str
    sha256: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ObjectStore(Protocol):
    async def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    def signed_url(self, key: str, *, expires_in: int = 300) -> str: ...


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}

    async def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        obj = StoredObject(
            key=key,
            data=data,
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )
        self._objects[key] = obj
        return obj

    async def get(self, key: str) -> bytes:
        if key not in self._objects:
            raise KeyError(key)
        return self._objects[key].data

    def signed_url(self, key: str, *, expires_in: int = 300) -> str:
        expiry = int(
            (datetime.now(UTC) + timedelta(seconds=expires_in)).timestamp()
        )
        return f"/signed/{key}?expires={expiry}&sig={uuid.uuid4().hex}"
