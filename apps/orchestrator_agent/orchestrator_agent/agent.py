from __future__ import annotations

# Patch mcp.types with missing classes from mcp-types before litellm imports them
import mcp.types
from typing import Any

if not hasattr(mcp.types, "CacheableResult"):
    from pydantic import BaseModel
    class CacheableResult(BaseModel):
        ttl_ms: int = 0
        cache_scope: str = "private"
    mcp.types.CacheableResult = CacheableResult

if not hasattr(mcp.types, "InputRequiredResult"):
    from pydantic import BaseModel
    class InputRequiredResult(BaseModel):
        input_requests: Any = None
        request_state: Any = None
        meta: Any = None
    mcp.types.InputRequiredResult = InputRequiredResult

# Patch version and methods submodules needed by litellm
if not hasattr(mcp.types, "version"):
    class _version:
        MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)
        HANDSHAKE_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
        LATEST_HANDSHAKE_VERSION = "2025-11-25"
    mcp.types.version = _version()

if not hasattr(mcp.types, "methods"):
    class _methods:
        CLIENT_REQUESTS = frozenset()
    mcp.types.methods = _methods()

from ag_ui_adk import AGUIToolset
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from orchestrator_agent.settings import Settings


def build_agent(settings: Settings) -> LlmAgent:
    model = LiteLlm(
        model=f"openai/{settings.nebius_model}",
        api_base=settings.nebius_base_url,
        api_key=settings.nebius_api_key,
    )
    return LlmAgent(
        name="MarketMeshOrchestrator",
        model=model,
        tools=[AGUIToolset()],
        instruction=(
            "You are the MarketMesh orchestrator. "
            "Use the MarketMesh Buyer A2A agent for sourcing, negotiation, ranking, and approval. "
            "Seller agents may be queried directly for status, but sourcing and award authority remain in the buyer. "
            "Never reveal or estimate the buyer's budget. "
            "When the buyer returns status approval_required, present the award and ask the user for approval. "
            "When the user approves, call MarketMesh Buyer again with JSON "
            '{"approval":{"approved":true,"approved_by":"Demo Buyer","note":"..."},"task_id":"..."}. '
            "When the user rejects, call MarketMesh Buyer with approved set to false. "
            "Call agents one at a time and wait for each result."
        ),
    )
