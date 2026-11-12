from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChallengeExtraction:
    code: str | None
    confidence: float
    simulated: bool = False
    provider: str = "unknown"
    raw: dict[str, object] | None = None


class ChallengeExtractor(Protocol):
    async def extract_code(
        self, image_bytes: bytes, *, expected_hint: str | None = None
    ) -> ChallengeExtraction: ...


class FixtureChallengeExtractor:
    """Sandbox/demo extractor.

    It does not perform vision/OCR; it accepts the caller-provided hint so the
    deterministic comparison path (issue -> match -> single-use -> expire) is
    exercised without a native OCR dependency.
    """

    async def extract_code(
        self, image_bytes: bytes, *, expected_hint: str | None = None
    ) -> ChallengeExtraction:
        _ = image_bytes
        return ChallengeExtraction(
            code=expected_hint,
            confidence=1.0 if expected_hint else 0.0,
            simulated=True,
            provider="fixture",
        )
