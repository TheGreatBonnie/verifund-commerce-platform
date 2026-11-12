from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from ag_ui_adk import AGUIToolset
from commerce_core.retrieval import NebiusEmbeddings, ProductRetriever
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool, ToolContext
from verifund_contracts import (
    CheckoutDecision,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
)

from orchestrator_agent import marketplace
from orchestrator_agent.mediation import mediate_seller_call as _mediate_seller_call
from orchestrator_agent.settings import Settings
from orchestrator_agent.verifund import (
    BuyerA2AAgents,
    SellerA2AClient,
    VerifundA2AClient,
    VerifundLifecycle,
    VerifundTaskHandle,
)

logger = logging.getLogger(__name__)

# NOTE: ag_ui_adk appends the CopilotKit middleware instructions after this
# string (see apps/console/app/api/copilotkit/[[...slug]]/route.ts). Keep the
# discovery and handoff rules in both places aligned.
MARKETMESH_ORCHESTRATOR_INSTRUCTION = """
# 1. Role and Mission

You are the MarketMesh orchestrator.

Coordinate the MarketMesh purchasing workflow by communicating
with the Buyer A2A agent, mediating seller calls, coordinating
human award approval, and reporting verified outcomes.

# 2. Authority and Non-Negotiable Rules

- The Buyer A2A agent owns sourcing, negotiation, ranking,
  and award decisions.
- Seller agents may be queried for status, but sourcing and
  award authority remain with the Buyer.
- Never reveal or estimate the Buyer's budget.
- Never alter the Buyer's task_id or award data.
- Never place an order before the Buyer confirms that the
  required approval has been granted.
- Never request award approval through plain chat text.
- Never call sellers directly. Use mediate_seller_call
  to handle Buyer seller_call pauses.
- Call agents sequentially. Wait for each result before
  proceeding to the next operation.

# 3. Buyer Interaction

Use the MarketMesh Buyer A2A agent for sourcing,
negotiation, ranking, and award decisions.

Inspect every structured Buyer response before choosing
the next action.

Do not send a separate Buyer message to continue sourcing
after mediate_seller_call has already resumed the
Buyer's checkpoint.

# 4. Seller Mediation Protocol

When the Buyer returns a seller_call pause, call
mediate_seller_call with the following mappings:

- buyer_task_id = task_id
- seller_card_url = card_url
- seller_request = request
- seller_id = seller_id, when present
- seller_name = seller_name, the seller's display name when present
- seller_task_id = seller_task_id, when present
- seller_context_id = seller_context_id, when present

The configured Buyer URL is supplied internally.
Do not pass seller_token; it is resolved automatically.

After mediation, inspect buyer_response and follow its
current status. Do not assume that the seller response
means the overall purchasing workflow is complete.

If buyer_response requests another seller call, mediate
that pause using the same procedure.

# 5. Product Discovery and Negotiation Handoff

Use search_marketplace_products only for discovery requests
(find, search, browse, or "what laptops do you have").

- Extract constraints. "$1500" or "under $1500" becomes
  max_unit_price_cents=150000; it is a per-unit ceiling in
  this demo.
- Put product or category terms in query (for example
  query="laptop"); do not pass filler words such as "good"
  or "me". Use use_case for intent hints and preferences
  for stated must-haves.
- Never route a discovery request to
  send_message_to_a2a_agent or to a seller. Discovery is
  read-only.
- Present only products and SKUs returned by the tool. Use
  match_rationale only to explain fields that were returned.
  Never invent a product, price, seller, or availability.
- When the user asks to negotiate for a shown card, read the
  SKU, name, unit price, and offers from the card or the user
  message. Do not search again unless the constraints changed.

Before starting sourcing, confirm the mandate. Ask only for
fields that are missing or ambiguous:

- quantity (default 1)
- budget ceiling or target, when the user states one
- delivery deadline
- warranty and returns requirements
- must-have attributes

Never re-ask a field the user already stated. A complete brief
starts immediately without extra questions.

When the brief is confirmed, call send_message_to_a2a_agent
with agentName="MarketMesh Buyer" and a task string containing
the confirmed mandate plus the grounded product context (SKU,
name, unit price, and offers). Keep the current thread; do not
navigate. Do not place an order or create an award, order, or
payment outcome. request_award_approval and all Verifund HITL
approvals remain mandatory.

# 6. Human Award Approval Protocol

When the Buyer returns status `approval_required`, follow these steps:

1. Extract the exact task_id, message, award, and mandate
   from the Buyer response.
2. Call the frontend `request_award_approval` tool with
   those exact values.
3. Do not ask for approval through plain chat text.
4. Wait for the actual tool result before continuing.
5. Proceed only when the returned decision explicitly
   confirms approval.

After approval, send the Buyer exactly this JSON payload,
with the approval decision nested under "approval" and the
original task_id at the top level:

{"approval": {"approved": true, "approved_by": "<approved_by>", "note": "<note>"}, "task_id": "<task_id>"}

Do not lift approved/approved_by/note to the top level, do
not rename "approval", and do not wrap the payload in prose.
The Buyer treats any message without the nested "approval"
key as a new sourcing brief, which starts a new run instead
of resuming the approved one.

Preserve the returned values exactly. Never substitute
a task ID, modify award data, or infer approval.

If the Buyer rejects the approval payload (for example,
"approval response requires task_id"), do not retry by
re-sending the brief or starting a new run. Report the
structured error and escalate instead.

If the approval response is missing required fields,
contains inconsistent identifiers, or does not clearly
confirm approval, do not resume the Buyer as approved.
Report or escalate the unresolved condition.

If the decision is rejected or otherwise not approved,
do not proceed with the award. Follow the supported
workflow for that decision; do not invent a new status.

# 7. Verifund Settlement Lifecycle Protocol

After the Buyer approves the award, follow this settlement
protocol instead of the legacy order flow.

- Call verifund_create_agreement only after the Buyer pauses
  with agreement_create_required. Pass the exact run_id, the
  original Buyer task and context, the flat award, the seller
  card URL, and the seller ID. The tool mediates the Buyer
  agreement review, the Seller agreement review, and the
  Buyer's recorded Seller decision. Never call the Seller
  directly and never invent a review.
- After verifund_create_agreement, inspect status and
  checkpoint before doing anything else.
- If status is input_required and checkpoint is
  buyer_approval_required and hitl.tool is exactly
  request_verifund_agreement_approval:
  1. Call request_verifund_agreement_approval with hitl.args
     unchanged. Do not rewrite the review URL or drop its
     query parameters; the full document remains available at
     agreement_review.review_url.
  2. Wait for the human decision from that HITL card. Do not
     call request_verifund_funding_approval, verifund_fund,
     or ask for a funding decision until the HITL resolves.
  3. Do not synthesize, guess, or reuse HITL arguments.
  4. Buyer approval happens through the HITL card, not via
     free-form chat text.
- Never render the funding HITL unless the latest tool result
  has status approval_required and hitl.tool is exactly
  request_verifund_funding_approval. Only then call that
  frontend tool with hitl.args unchanged, and pass those exact
  values to the frontend; do not reconstruct them from chat
  text.
- If the user says they approved the agreement, call
  verifund_status with the exact task_id, context_id, and
  run_id from the review tool result. If it now returns
  approval_required with hitl.tool
  request_verifund_funding_approval, render that HITL.
- When the human funding decision returns, call verifund_fund
  with the structured FundingApprovalDecision. Free-form chat
  text never authorizes funding.
- If hitl.tool is request_verifund_paypal_checkout, call that
  frontend tool with hitl.args unchanged and wait for the card.
  When the card returns, call verifund_checkout with the exact
  status, transaction_id, idempotency_key, order_id, capture_id,
  and projection from the card result. Never call verifund_checkout
  unless the card result itself has status completed with a real
  order_id and capture_id; free-form confirmation text is not a
  checkout result. The verifund agent verifies
  the settlement with the Buyer; never substitute or invent a
  funded state. If the checkout result is missing order/capture
  ids, re-present the checkout card instead of recording it.
  Never call verifund_evidence_review while settlement is pending;
  resume on the next status refresh instead.
- After funding, call verifund_evidence_review with the same
  task_id, context_id, run_id, and seller_card_url. It places
  the purchase order with the Seller and polls funding and
  evidence. Do not call the Seller or place the purchase order
  yourself.
- When hitl.tool is request_verifund_release_approval, call that
  frontend tool with hitl.args unchanged, then call verifund_release
  with the structured ReleaseApprovalDecision. A rejected release
  is a manual-review outcome, not a success.
- Call verifund_receipt after release when the receipt is not
  already attached. Never claim a payout or receipt exists unless
  the tool result confirms it.
- Treat working, pending, input_required, failed, and malformed
  results as non-success. Preserve the exact task_id, context_id,
  run_id, agreement_hash, and transaction_id from the tool result.
- Do not use the legacy funding, release, purchase-order, evidence,
  or receipt steps outside this protocol; the Buyer graph ends at
  the bilateral agreement.

# 8. Result and Error Handling

- If the Buyer or mediation result indicates complete,
  report the verified result.
- If the Buyer requests another seller call, mediate it.
- If the Buyer returns approval_required, follow the
  approval protocol above.
- When reporting a failure, preserve the exact structured
  error returned by the Buyer or seller.
- Do not infer offer expiration unless the structured
  error explicitly identifies offer expiration.
- Do not claim the user was charged or was not charged
  unless the system response confirms it.
- If a response has an unknown status or lacks required
  fields, do not invent a successful outcome. Report the
  uncertainty and use the supported recovery procedure.

# 9. Final Response

Report outcomes based on confirmed system responses.
Distinguish completed purchases from pending approvals,
failed operations, and unresolved states.

Never claim that an approval, order, or payment succeeded
unless the corresponding system result confirms it.
"""



def _build_mediation_tool(settings: Settings) -> FunctionTool:
    async def mediate_seller_call(
        buyer_task_id: str,
        seller_card_url: str,
        seller_request: dict | None = None,
        seller_id: str | None = None,
        seller_name: str | None = None,
        seller_task_id: str | None = None,
        seller_context_id: str | None = None,
        settlement_secret_ref: dict | None = None,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """Call a seller and resume the buyer's checkpoint with its response."""
        thread_id = (
            getattr(getattr(tool_context, "session", None), "id", None)
            or buyer_task_id
        )
        result = await _mediate_seller_call(
            buyer_task_id=buyer_task_id,
            seller_card_url=seller_card_url,
            buyer_a2a_url=settings.buyer_a2a_url,
            seller_request=seller_request,
            seller_id=seller_id,
            seller_task_id=seller_task_id,
            seller_context_id=seller_context_id or thread_id,
            buyer_context_id=thread_id,
            settlement_secret_ref=settlement_secret_ref,
            buyer_internal_url=settings.buyer_internal_url,
            buyer_internal_token=settings.buyer_internal_token,
            buyer_internal_timeout_seconds=settings.buyer_internal_timeout_seconds,
            control_plane_url=settings.verifund_control_plane_url,
        )
        if seller_name and isinstance(result, dict):
            result.setdefault("seller_name", seller_name)
        return result

    return FunctionTool(mediate_seller_call)


def _build_marketplace_search_tool(
    settings: Settings,
    *,
    retriever: ProductRetriever | None = None,
) -> FunctionTool:
    if retriever is None and settings.nebius_api_key:
        retriever = ProductRetriever(
            NebiusEmbeddings(
                api_key=settings.nebius_api_key,
                base_url=settings.nebius_base_url,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            ),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    async def search_marketplace_products(
        # ADK's automatic function parser does not understand PEP 604 unions.
        query: Optional[str] = None,  # noqa: UP045
        category: Optional[str] = None,  # noqa: UP045
        max_unit_price_cents: Optional[int] = None,  # noqa: UP045
        in_stock_only: bool = False,
        use_case: Optional[str] = None,  # noqa: UP045
        preferences: Optional[list[str]] = None,  # noqa: UP045
        limit: int = 12,
    ) -> dict:
        """Find products from MarketMesh sellers for a grounded purchase search."""
        if retriever is None:
            return {
                "error": "retrieval_unavailable",
                "message": "Product search is temporarily unavailable",
            }
        try:
            products = await marketplace.fetch_marketplace_products(
                base_url=settings.buyer_internal_url,
                internal_token=settings.buyer_internal_token,
                timeout=settings.buyer_internal_timeout_seconds,
                category=category or None,
            )
        except Exception:
            logger.exception("marketplace catalog fetch failed")
            return {
                "error": "marketplace_unavailable",
                "message": "Marketplace catalog is unavailable",
            }

        ceiling: int | None
        try:
            ceiling = (
                int(max_unit_price_cents)
                if max_unit_price_cents is not None
                else None
            )
        except (TypeError, ValueError):
            ceiling = None
        try:
            effective_limit = int(limit)
        except (TypeError, ValueError):
            effective_limit = 12
        effective_limit = max(1, min(effective_limit, 24))

        try:
            ranked, trace = marketplace.retrieve_products(
                products,
                retriever=retriever,
                query=query,
                category=category,
                max_unit_price_cents=ceiling,
                in_stock_only=bool(in_stock_only),
                use_case=use_case,
                preferences=preferences,
            )
        except Exception:
            logger.exception("product retrieval failed")
            return {
                "error": "retrieval_unavailable",
                "message": "Product search is temporarily unavailable",
            }

        return marketplace.shape_search_result(
            {
                "query": query,
                "category": category,
                "max_unit_price_cents": ceiling,
                "in_stock_only": bool(in_stock_only),
                "use_case": use_case,
                "preferences": preferences or [],
                "limit": effective_limit,
            },
            ranked,
            effective_limit,
            retrieval=trace,
        )

    return FunctionTool(search_marketplace_products)


def build_verifund_lifecycle(settings: Settings) -> VerifundLifecycle:
    return VerifundLifecycle(
        verifund=VerifundA2AClient(
            base_url=settings.verifund_agent_url,
            token=settings.verifund_agent_a2a_token,
        ),
        buyer=BuyerA2AAgents(buyer_a2a_url=settings.buyer_a2a_url),
        seller=SellerA2AClient(
            control_plane_url=settings.verifund_control_plane_url,
            buyer_internal_token=settings.buyer_internal_token,
        ),
        buyer_internal_url=settings.buyer_internal_url,
        buyer_internal_token=settings.buyer_internal_token,
        buyer_internal_timeout_seconds=(
            settings.buyer_internal_timeout_seconds
        ),
    )


def _build_verifund_tools(settings: Settings) -> list[FunctionTool]:
    lifecycle = build_verifund_lifecycle(settings)

    def handle(
        task_id: str, context_id: str, run_id: str
    ) -> VerifundTaskHandle:
        return VerifundTaskHandle(task_id, context_id, run_id)

    async def verifund_create_agreement(
        run_id: str,
        buyer_task_id: str,
        buyer_context_id: str,
        award: dict,
        seller_card_url: str,
        seller_id: str,
    ) -> dict:
        """Start the Verifund lifecycle and complete the bilateral review."""
        return await lifecycle.start(
            run_id=run_id,
            award=award,
            buyer_task_id=buyer_task_id,
            buyer_context_id=buyer_context_id,
            seller_card_url=seller_card_url,
            seller_id=seller_id,
            idempotency_key=f"agreement:{run_id}:{award.get('offer_id')}",
        )

    async def verifund_status(
        task_id: str, context_id: str, run_id: str
    ) -> dict:
        """Return the current Verifund checkpoint without advancing it."""
        return await lifecycle.status(handle(task_id, context_id, run_id))

    async def verifund_fund(
        task_id: str,
        context_id: str,
        run_id: str,
        decision: dict,
    ) -> dict:
        """Resume the funding checkpoint with a structured human decision."""
        return await lifecycle.resume_funding(
            handle(task_id, context_id, run_id),
            FundingApprovalDecision.model_validate(decision),
        )

    async def verifund_checkout(
        task_id: str,
        context_id: str,
        run_id: str,
        status: Literal["completed", "canceled", "fallback"],
        transaction_id: str,
        idempotency_key: str,
        # ADK's automatic function parser does not understand PEP 604 unions.
        projection: Optional[dict[str, Any]] = None,  # noqa: UP045
        order_id: Optional[str] = None,  # noqa: UP045
        capture_id: Optional[str] = None,  # noqa: UP045
    ) -> dict:
        """Resume the checkout checkpoint with the embedded card result."""
        decision = CheckoutDecision(
            status=status,
            transaction_id=transaction_id,
            order_id=order_id or None,
            capture_id=capture_id or None,
            projection=projection or {},
            idempotency_key=idempotency_key,
        )
        return await lifecycle.resume_checkout(
            handle(task_id, context_id, run_id),
            decision,
        )

    async def verifund_evidence_review(
        task_id: str,
        context_id: str,
        run_id: str,
        seller_card_url: str,
    ) -> dict:
        """Place the purchase order and poll funding, evidence, or release."""
        return await lifecycle.advance(
            handle(task_id, context_id, run_id),
            seller_card_url=seller_card_url,
        )

    async def verifund_release(
        task_id: str,
        context_id: str,
        run_id: str,
        decision: dict,
    ) -> dict:
        """Resume the release checkpoint with a structured human decision."""
        return await lifecycle.resume_release(
            handle(task_id, context_id, run_id),
            ReleaseApprovalDecision.model_validate(decision),
        )

    async def verifund_receipt(
        task_id: str, context_id: str, run_id: str, transaction_id: str
    ) -> dict:
        """Return the verified receipt after release."""
        return await lifecycle.receipt(
            handle(task_id, context_id, run_id),
            transaction_id=transaction_id,
        )

    return [
        FunctionTool(verifund_create_agreement),
        FunctionTool(verifund_status),
        FunctionTool(verifund_fund),
        FunctionTool(verifund_checkout),
        FunctionTool(verifund_evidence_review),
        FunctionTool(verifund_release),
        FunctionTool(verifund_receipt),
    ]


def build_agent(settings: Settings) -> LlmAgent:
    model = LiteLlm(
        model=f"openai/{settings.nebius_model}",
        api_base=settings.nebius_base_url,
        api_key=settings.nebius_api_key,
        _skip_mcp_handler=True,
    )
    tools = [
        _build_mediation_tool(settings),
        _build_marketplace_search_tool(settings),
        AGUIToolset(),
    ]
    if settings.verifund_mode != "off":
        tools.extend(_build_verifund_tools(settings))
    return LlmAgent(
        name="marketmesh_orchestrator",
        model=model,
        tools=tools,
        instruction=MARKETMESH_ORCHESTRATOR_INSTRUCTION,
    )
