from __future__ import annotations

from typing import Any

from verifund_contracts import VerifundTaskRequest, VerifundTaskResult

from verifund_agent.client import BuyerInternalClient


class VerifundAgentService:
    def __init__(
        self, *, graph: Any, buyer: BuyerInternalClient
    ) -> None:
        self.graph = graph
        self.buyer = buyer

    async def handle(
        self,
        request: VerifundTaskRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> VerifundTaskResult:
        return VerifundTaskResult(
            skill=request.skill,
            status="failed",
            task_id=task_id,
            run_id=request.run_id,
            transaction_id=request.transaction_id,
            agreement_version=request.agreement_version,
            agreement_hash=request.agreement_hash,
            message="unsupported Verifund skill",
        )
