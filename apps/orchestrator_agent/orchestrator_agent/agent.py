from __future__ import annotations

from ag_ui_adk import AGUIToolset
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool

from orchestrator_agent.mediation import mediate_seller_call as _mediate_seller_call
from orchestrator_agent.settings import Settings


def _build_mediation_tool(settings: Settings) -> FunctionTool:
    async def mediate_seller_call(
        buyer_task_id: str,
        seller_card_url: str,
        seller_request: dict | None = None,
        seller_id: str | None = None,
        seller_task_id: str | None = None,
        seller_context_id: str | None = None,
    ) -> dict:
        """Call a seller and resume the buyer's checkpoint with its response."""
        return await _mediate_seller_call(
            buyer_task_id=buyer_task_id,
            seller_card_url=seller_card_url,
            buyer_a2a_url=settings.buyer_a2a_url,
            seller_request=seller_request,
            seller_id=seller_id,
            seller_task_id=seller_task_id,
            seller_context_id=seller_context_id,
        )

    return FunctionTool(mediate_seller_call)


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
        tools=[_build_mediation_tool(settings), AGUIToolset()],
        instruction=(
            "You are the MarketMesh orchestrator. "
            "Use the MarketMesh Buyer A2A agent for sourcing, negotiation, ranking, and approval. "
            "Seller agents may be queried directly for status, but sourcing and award authority remain in the buyer. "
            "Never reveal or estimate the buyer's budget. "
            "When the buyer returns status approval_required, present the award and ask the user for approval. "
            "When the user approves, call MarketMesh Buyer again with JSON "
            '{"approval":{"approved":true,"approved_by":"Demo Buyer","note":"..."},"task_id":"..."}. '
            "When the user rejects, call MarketMesh Buyer with approved set to false. "
            "Call agents one at a time and wait for each result. "
            "Use mediate_seller_call to handle buyer seller_call pauses. Pass buyer_task_id from task_id, seller_id, seller_card_url from card_url, seller_request from request, and seller_task_id and seller_context_id when present. The configured buyer URL is supplied internally. Do not pass seller_token (it is resolved automatically). This tool calls the seller and resumes the same Buyer checkpoint; inspect its buyer_response to decide the next step. Do not send a separate Buyer message to continue sourcing after mediation. If buyer_response requests another seller call, mediate that pause; if it requires approval, ask the user; if it is complete, report the result. Never call sellers directly from the prompt."
        ),
    )
