from __future__ import annotations

import json
from typing import Any

import httpx
from verifund_contracts import Requirement


class SettlementError(Exception):
    def __init__(
        self, code: str, message: str, *, status_code: int = 0
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_mandate(
    requirements: list[Requirement],
) -> None:
    """Validate the buyer-authored requirement catalog against the seller mandate.

    Raises ``ValueError`` when a seller-owned requirement can never reach a
    settled outcome. The floor-undetectable case (spec §8 risk note) is
    ``operator=eq`` on an unobservable value. The catalog types checks by
    ``verification_method`` and ``ai_derived``; extraction is fuzzy, so an
    exact literal comparison flagged as *not* AI-derived is treated by the
    pipeline as a deterministic compare against OCR/AI output — it can never
    settle cleanly and pins the requirement in perpetual remediation. That
    combination is rejected here, as is any check whose
    ``verification_method`` has no evaluator.

    Allowed: deterministic checks; AI-derived extraction checks (these roll up
    as REVIEW for a human, which the mandate tolerates); agreement-derived
    checks (``ai_derived`` with no literal ``expected_value``); and tolerant
    operators (``gte``/``lte``/``contains``) and ``exists``.
    """
    known_methods = {"deterministic", "extraction"}
    problems: list[str] = []
    for req in requirements:
        if getattr(req, "owner", "seller") != "seller":
            # The mandate covers what the seller must produce; system- and
            # buyer-owned requirements are not the seller's to satisfy.
            continue
        for check in req.checks:
            method = check.verification_method
            label = f"{req.requirement_id}.{check.check_id}"
            if method not in known_methods:
                problems.append(
                    f"{label}: no evaluator for verification_method {method!r}"
                )
                continue
            if (
                check.operator == "eq"
                and method == "extraction"
                and not check.ai_derived
                and check.expected_value is not None
            ):
                problems.append(
                    f"{label}: operator=eq on an unobservable value "
                    f"(expected_value={check.expected_value!r} via extraction); "
                    "the seller cannot satisfy it"
                )
    if problems:
        raise ValueError(
            "unsatisfiable requirement(s) in the agreement catalog: "
            + "; ".join(problems)
        )


def encode_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class SellerSettlementClient:
    """Control-plane seller API client using internal service auth.

    Migrated routes require `X-Verifund-Internal-Token` plus explicit seller
    context (`X-Seller-Org-Id` and/or `X-Seller-Id`). Legacy per-transaction
    bearer seller tokens are not accepted.
    """

    def __init__(
        self,
        base_url: str,
        *,
        internal_token: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(
        self, *, organization_id: str | None = None, seller_id: str | None = None
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.internal_token:
            headers["x-verifund-internal-token"] = self.internal_token
        if organization_id:
            headers["x-seller-org-id"] = organization_id
        if seller_id:
            headers["x-seller-id"] = seller_id
        return headers

    async def get_transaction(
        self,
        transaction_id: str,
        *,
        organization_id: str | None = None,
        seller_id: str | None = None,
    ) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers=self._headers(
                organization_id=organization_id, seller_id=seller_id
            ),
        )
        if response.status_code >= 400:
            raise SettlementError(
                "unauthorized" if response.status_code == 401 else "invalid_request",
                "seller transaction lookup failed",
                status_code=response.status_code,
            )
        return response.json()

    async def upload_evidence(
        self,
        transaction_id: str,
        *,
        organization_id: str | None = None,
        seller_id: str | None = None,
        requirement_id: str,
        content: bytes | None = None,
        media_type: str | None = None,
        filename: str | None = None,
        reference: str | None = None,
        reference_type: str | None = None,
        note: str = "",
        captured_at: str | None = None,
        agreement_version: int | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"requirement_id": requirement_id}
        if note:
            data["note"] = note
        if captured_at:
            data["captured_at"] = captured_at
        if agreement_version is not None:
            data["agreement_version"] = str(agreement_version)
        files = None
        if content is not None:
            files = {
                "file": (
                    filename or f"{requirement_id}.bin",
                    content,
                    media_type or "application/octet-stream",
                )
            }
        elif reference is not None:
            data["reference"] = reference
            if reference_type:
                data["reference_type"] = reference_type
        response = await self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers=self._headers(
                organization_id=organization_id, seller_id=seller_id
            ),
            data=data,
            files=files,
        )
        if response.status_code >= 400:
            raise SettlementError(
                "invalid_request",
                "evidence upload failed",
                status_code=response.status_code,
            )
        return response.json()

    async def get_evidence(
        self,
        transaction_id: str,
        evidence_id: str,
        *,
        organization_id: str | None = None,
        seller_id: str | None = None,
    ) -> tuple[bytes, str]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence/{evidence_id}",
            headers=self._headers(
                organization_id=organization_id, seller_id=seller_id
            ),
        )
        if response.status_code >= 400:
            raise SettlementError(
                "not_found",
                "evidence not found",
                status_code=response.status_code,
            )
        return response.content, response.headers.get(
            "content-type", "application/octet-stream"
        )
