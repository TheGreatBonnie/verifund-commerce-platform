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
    def __init__(self, base_url: str, *, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, token: str) -> dict[str, str]:
        return {"authorization": f"Bearer {token}"}

    async def get_transaction(
        self, token: str, transaction_id: str
    ) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers=self._headers(token),
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
        token: str,
        transaction_id: str,
        *,
        kind: str,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        data = {"kind": kind}
        if note:
            data["note"] = note
        if captured_at:
            data["captured_at"] = captured_at
        response = await self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers=self._headers(token),
            data=data,
            files={"file": (filename, content, media_type)},
        )
        if response.status_code >= 400:
            raise SettlementError(
                "invalid_request",
                "evidence upload failed",
                status_code=response.status_code,
            )
        return response.json()

    async def get_evidence(
        self, token: str, transaction_id: str, evidence_id: str
    ) -> tuple[bytes, str]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence/{evidence_id}",
            headers=self._headers(token),
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
