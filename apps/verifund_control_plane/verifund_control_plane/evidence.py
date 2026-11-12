from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from verifund_contracts import EvidenceItem, EvidenceKind

from verifund_control_plane.errors import VerifundError

ALLOWED_MEDIA_TYPES = {
    "application/json",
    "text/plain",
    "text/csv",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "video/webm",
    "video/quicktime",
    "video/mp4",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvidenceStore:
    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, sha256: str) -> Path:
        if not SHA256_PATTERN.match(sha256):
            raise VerifundError(
                "invalid_request", "invalid evidence hash", status_code=400
            )
        return self.root / sha256

    def _key(
        self, organization_id: str, transaction_id: str, sha256: str
    ) -> str:
        return f"tenants/{organization_id}/transactions/{transaction_id}/{sha256}"

    def verification_key(
        self, organization_id: str, document_id: str, sha256: str
    ) -> str:
        return f"tenants/{organization_id}/verification/{document_id}/{sha256}"

    def _path_for_key(self, storage_key: str) -> Path:
        if ".." in Path(storage_key).parts or storage_key.startswith("/"):
            raise VerifundError(
                "invalid_request", "invalid evidence hash", status_code=400
            )
        return self.root / storage_key

    async def put(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str,
        media_type: str,
        original_filename: str,
        data: bytes,
        note: str | None,
        captured_at: datetime | None,
        organization_id: str | None = None,
    ) -> EvidenceItem:
        try:
            EvidenceKind(kind)
        except ValueError as exc:
            raise VerifundError(
                "invalid_request", f"unsupported evidence kind: {kind}", status_code=400
            ) from exc
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise VerifundError(
                "unsupported_media_type",
                f"unsupported media type: {media_type}",
                status_code=415,
            )
        if not data:
            raise VerifundError(
                "invalid_request", "evidence file is empty", status_code=400
            )
        if len(data) > self.max_bytes:
            raise VerifundError(
                "evidence_too_large",
                f"evidence exceeds {self.max_bytes} bytes",
                status_code=413,
            )
        digest = hashlib.sha256(data).hexdigest()
        storage_key: str | None = None
        if organization_id:
            storage_key = self._key(organization_id, transaction_id, digest)
            path = self._path_for_key(storage_key)
        else:
            path = self._path(digest)
        if not path.exists():
            await asyncio.to_thread(self._write_atomic, path, data)
        return EvidenceItem(
            evidence_id=f"ev_{uuid.uuid4().hex}",
            kind=kind,
            sha256=digest,
            media_type=media_type,
            size_bytes=len(data),
            original_filename=original_filename or "evidence",
            note=note,
            created_at=datetime.now().astimezone(),
            storage_key=storage_key,
            organization_id=organization_id,
        )

    def _write_atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def read(self, sha256: str, storage_key: str | None = None) -> bytes:
        candidates: list[Path] = []
        if storage_key:
            candidates.append(self._path_for_key(storage_key))
        legacy = self._path(sha256)
        if legacy not in candidates:
            candidates.append(legacy)
        for path in candidates:
            if path.exists():
                return path.read_bytes()
        raise VerifundError(
            "not_found", "evidence content is missing", status_code=404
        )

    def verify(self, sha256: str, storage_key: str | None = None) -> bool:
        try:
            raw = self.read(sha256, storage_key)
        except (VerifundError, OSError, ValueError):
            return False
        return hashlib.sha256(raw).hexdigest() == sha256
