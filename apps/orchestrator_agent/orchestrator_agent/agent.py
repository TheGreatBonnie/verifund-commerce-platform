from __future__ import annotations

from ag_ui_adk import AGUIToolset
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from orchestrator_agent.settings import Settings


def build_agent(settings: Settings) -> LlmAgent:
    model = LiteLlm(
        model=f"openai/{settings.nebius_model}",
        api_base=settings.nebius_base_url,
        api_key=settings.nebius_api_key,
        _skip_mcp_handler=True,
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
