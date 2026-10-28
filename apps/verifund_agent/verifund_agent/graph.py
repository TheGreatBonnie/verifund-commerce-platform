from __future__ import annotations

from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph


class VerifundState(TypedDict, total=False):
    task_id: str
    context_id: str
    run_id: str
    transaction_id: str
    agreement_version: int
    agreement_hash: str
    seller_token_ref: str
    award: dict
    buyer_task_id: str
    buyer_context_id: str
    agreement: dict
    buyer_review: dict
    seller_decision: dict
    funding_approval: dict
    funding_projection: dict
    checkout_url: str
    expires_at: str
    purchase_order: dict
    order: dict
    evidence: dict
    verification: dict
    release_approval: dict
    release_projection: dict
    projection: dict
    receipt: dict
    checkpoint: str
    approval_type: str
    stage: str
    error: str


async def initialize(state: VerifundState, config: RunnableConfig) -> dict:
    return {"stage": "initialized"}


def build_graph(checkpointer):
    builder = StateGraph(VerifundState)
    builder.add_node("initialize", initialize)
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", END)
    return builder.compile(checkpointer=checkpointer)
