from typing import Any, cast

from langgraph.types import Command
from pydantic import ValidationError
from verifund_contracts import (
    TransactionState,
    VerifundCheckpoint,
    VerifundResumeRequest,
    VerifundSkill,
    VerifundTaskRequest,
    VerifundTaskResult,
)

from verifund_agent.client import BuyerAPIError, BuyerInternalClient
from verifund_agent.graph import (
    PENDING_CHECKPOINTS,
    VerifundProtocolError,
    VerifundState,
    buyer_approval_payload,
    change_resolution_payload,
    evidence_pending_payload,
    funding_approval_payload,
    funding_pending_payload,
    purchase_order_payload,
    release_approval_payload,
    seller_operator_payload,
    seller_review_payload,
)

CHECKPOINT_ORDER = {
    VerifundCheckpoint.SELLER_REVIEW_REQUIRED: 1,
    VerifundCheckpoint.SELLER_OPERATOR_REQUIRED: 2,
    VerifundCheckpoint.BUYER_APPROVAL_REQUIRED: 3,
    VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED: 4,
    VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED: 5,
    VerifundCheckpoint.FUNDING_PENDING: 6,
    VerifundCheckpoint.PURCHASE_ORDER_REQUIRED: 7,
    VerifundCheckpoint.EVIDENCE_PENDING: 8,
    VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED: 9,
}

CHECKPOINT_SKILLS = {
    VerifundCheckpoint.SELLER_REVIEW_REQUIRED: VerifundSkill.AGREEMENT_CREATE,
    VerifundCheckpoint.SELLER_OPERATOR_REQUIRED: VerifundSkill.AGREEMENT_CREATE,
    VerifundCheckpoint.BUYER_APPROVAL_REQUIRED: VerifundSkill.AGREEMENT_CREATE,
    VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED: VerifundSkill.AGREEMENT_CREATE,
    VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED: VerifundSkill.TRANSACTION_FUND,
    VerifundCheckpoint.FUNDING_PENDING: VerifundSkill.TRANSACTION_FUND,
    VerifundCheckpoint.PURCHASE_ORDER_REQUIRED: VerifundSkill.TRANSACTION_FUND,
    VerifundCheckpoint.EVIDENCE_PENDING: VerifundSkill.EVIDENCE_REVIEW,
    VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED: VerifundSkill.TRANSACTION_RELEASE,
}

PAYLOAD_BUILDERS = {
    VerifundCheckpoint.SELLER_REVIEW_REQUIRED: seller_review_payload,
    VerifundCheckpoint.SELLER_OPERATOR_REQUIRED: seller_operator_payload,
    VerifundCheckpoint.BUYER_APPROVAL_REQUIRED: buyer_approval_payload,
    VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED: change_resolution_payload,
    VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED: funding_approval_payload,
    VerifundCheckpoint.FUNDING_PENDING: funding_pending_payload,
    VerifundCheckpoint.PURCHASE_ORDER_REQUIRED: purchase_order_payload,
    VerifundCheckpoint.EVIDENCE_PENDING: evidence_pending_payload,
    VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED: release_approval_payload,
}

CHECKPOINT_STATES = {
    VerifundCheckpoint.SELLER_REVIEW_REQUIRED: TransactionState.AWARDED,
    VerifundCheckpoint.SELLER_OPERATOR_REQUIRED: TransactionState.AWARDED,
    VerifundCheckpoint.BUYER_APPROVAL_REQUIRED: TransactionState.AWARDED,
    VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED: TransactionState.AWARDED,
    VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED: TransactionState.AGREED,
    VerifundCheckpoint.FUNDING_PENDING: TransactionState.FUNDING_PENDING,
    VerifundCheckpoint.PURCHASE_ORDER_REQUIRED: TransactionState.FUNDED,
    VerifundCheckpoint.EVIDENCE_PENDING: TransactionState.FULFILLMENT_PENDING,
    VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED: TransactionState.RELEASE_PERMITTED,
}

POLLED_CHECKPOINTS = {
    VerifundCheckpoint.FUNDING_PENDING,
    VerifundCheckpoint.EVIDENCE_PENDING,
}


class VerifundAgentService:
    def __init__(
        self, *, graph: Any, buyer: BuyerInternalClient
    ) -> None:
        self.graph = graph
        self.buyer = buyer

    def _config(self, context_id: str) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": context_id,
                "buyer": self.buyer,
            }
        }

    async def handle(
        self,
        request: VerifundTaskRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> VerifundTaskResult:
        try:
            if request.skill == VerifundSkill.AGREEMENT_CREATE:
                return await self._agreement_create(
                    request, task_id=task_id, context_id=context_id
                )
            if request.skill == VerifundSkill.TRANSACTION_STATUS:
                return await self._transaction_status(
                    request, task_id=task_id, context_id=context_id
                )
            if request.skill == VerifundSkill.RECEIPT_GET:
                return await self._receipt_get(request, task_id=task_id)
        except BuyerAPIError as exc:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message=str(exc),
                retryable=exc.retryable,
            )
        except (VerifundProtocolError, ValidationError) as exc:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message=str(exc),
            )
        return self._failed(
            skill=request.skill,
            task_id=task_id,
            run_id=request.run_id,
            message="skill is not available at this lifecycle stage",
        )

    async def resume(
        self,
        resume: VerifundResumeRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> VerifundTaskResult:
        skill = CHECKPOINT_SKILLS[resume.checkpoint]
        if resume.task_id != task_id:
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message="resume task does not match the A2A task",
            )
        config = self._config(context_id)
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values:
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message="no lifecycle task exists for this resume",
            )
        if snapshot.values.get("run_id") != resume.run_id:
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message="resume run does not match the lifecycle task",
            )
        current = self._pending(snapshot)
        if current is None:
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message="the lifecycle task is not waiting at a checkpoint",
            )
        if resume.checkpoint != current:
            if CHECKPOINT_ORDER.get(resume.checkpoint, 99) < CHECKPOINT_ORDER[current]:
                return self._snapshot_result(
                    snapshot, skill=skill, task_id=task_id
                )
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message=(
                    f"resume checkpoint {resume.checkpoint} does not match "
                    f"the pending {current}"
                ),
            )
        try:
            output = await self.graph.ainvoke(
                Command(resume=resume.value), config
            )
        except BuyerAPIError as exc:
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message=str(exc),
                retryable=exc.retryable,
            )
        except (VerifundProtocolError, ValidationError) as exc:
            return self._failed(
                skill=skill,
                task_id=task_id,
                run_id=resume.run_id,
                message=str(exc),
            )
        return self._output_result(
            output, skill=skill, task_id=task_id, run_id=resume.run_id
        )

    async def get_agreement(self, context_id: str) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self._config(context_id))
        if not snapshot.values:
            return {}
        agreement = snapshot.values.get("agreement")
        return agreement if isinstance(agreement, dict) else {}

    async def resume_agreement(self, resume, *, task_id, context_id):
        return await self.resume(resume, task_id=task_id, context_id=context_id)

    def _pending(self, snapshot: Any) -> VerifundCheckpoint | None:
        for node in snapshot.next:
            if node in PENDING_CHECKPOINTS:
                return PENDING_CHECKPOINTS[node]
        return None

    async def _agreement_create(
        self,
        request: VerifundTaskRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> VerifundTaskResult:
        award = request.payload.get("award") or {}
        if award.get("run_id") != request.run_id:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message="award run does not match the task run",
            )
        buyer_task_id = str(request.payload.get("buyer_task_id") or "")
        buyer_context_id = str(request.payload.get("buyer_context_id") or "")
        if not buyer_task_id or not buyer_context_id:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message="agreement requires the original Buyer task and context",
            )
        config = self._config(context_id)
        snapshot = await self.graph.aget_state(config)
        if snapshot.values:
            if snapshot.values.get("run_id") != request.run_id:
                return self._failed(
                    skill=request.skill,
                    task_id=task_id,
                    run_id=request.run_id,
                    message=(
                        "This conversation already has a lifecycle task. "
                        "Start a new conversation."
                    ),
                )
            return self._snapshot_result(
                snapshot, skill=request.skill, task_id=task_id
            )
        output = await self.graph.ainvoke(
            {
                "task_id": task_id,
                "context_id": context_id,
                "run_id": request.run_id,
                "award": award,
                "buyer_task_id": buyer_task_id,
                "buyer_context_id": buyer_context_id,
                "stage": "initialized",
            },
            config,
        )
        return self._output_result(
            output, skill=request.skill, task_id=task_id, run_id=request.run_id
        )

    async def _transaction_status(
        self,
        request: VerifundTaskRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> VerifundTaskResult:
        snapshot = await self.graph.aget_state(self._config(context_id))
        if not snapshot.values:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message="no lifecycle task exists for this run",
            )
        if snapshot.values.get("run_id") != request.run_id:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message="run does not match the lifecycle task",
            )
        pending = self._pending(snapshot)
        if pending in POLLED_CHECKPOINTS:
            projection = await self._settlement_projection(
                snapshot, request=request
            )
            if self._poll_is_ready(pending, projection):
                output = await self.graph.ainvoke(
                    Command(resume={"projection": projection}),
                    self._config(context_id),
                )
                return self._output_result(
                    output,
                    skill=request.skill,
                    task_id=task_id,
                    run_id=request.run_id,
                )
            values = dict(snapshot.values)
            if pending is VerifundCheckpoint.FUNDING_PENDING:
                values["funding_projection"] = projection
            else:
                values["projection"] = projection
            payload = PAYLOAD_BUILDERS[pending](cast(VerifundState, values))
            return self._checkpoint_result(
                payload,
                checkpoint=pending,
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
            )
        return self._snapshot_result(
            snapshot, skill=request.skill, task_id=task_id
        )

    async def _settlement_projection(
        self, snapshot: Any, *, request: VerifundTaskRequest
    ) -> dict[str, Any]:
        view = await self.buyer.get_settlement(
            str(snapshot.values.get("run_id") or request.run_id)
        )
        projection = view.get("projection") or {}
        expected = snapshot.values.get("transaction_id") or request.transaction_id
        if projection.get("transaction_id") != expected:
            raise VerifundProtocolError(
                "buyer settlement does not match the lifecycle transaction"
            )
        return projection

    @staticmethod
    def _poll_is_ready(
        pending: VerifundCheckpoint, projection: dict[str, Any]
    ) -> bool:
        state = projection.get("state")
        if pending is VerifundCheckpoint.FUNDING_PENDING:
            return state == TransactionState.FUNDED.value
        return state in {
            TransactionState.RELEASE_PERMITTED.value,
            TransactionState.REVIEW_REQUIRED.value,
        }

    async def _receipt_get(
        self, request: VerifundTaskRequest, *, task_id: str
    ) -> VerifundTaskResult:
        receipt = await self.buyer.receipt(request.run_id)
        payload = receipt.get("payload") or {}
        verified = receipt.get("verified") is True
        return VerifundTaskResult(
            skill=request.skill,
            status="completed",
            task_id=task_id,
            run_id=request.run_id,
            transaction_id=payload.get("transaction_id")
            or request.transaction_id,
            agreement_hash=payload.get("agreement_hash") or request.agreement_hash,
            state=TransactionState.RELEASED if verified else None,
            data={"receipt": receipt},
            message=(
                "Verified receipt retrieved."
                if verified
                else "Receipt retrieved but not verified."
            ),
        )

    def _snapshot_result(
        self,
        snapshot: Any,
        *,
        skill: VerifundSkill,
        task_id: str,
    ) -> VerifundTaskResult:
        pending = self._pending(snapshot)
        if pending is not None:
            payload = PAYLOAD_BUILDERS[pending](
                cast(VerifundState, dict(snapshot.values))
            )
            return self._checkpoint_result(
                payload,
                checkpoint=pending,
                skill=skill,
                task_id=task_id,
                run_id=str(snapshot.values.get("run_id") or ""),
            )
        return self._completed_result(
            dict(snapshot.values),
            skill=skill,
            task_id=task_id,
            run_id=str(snapshot.values.get("run_id") or ""),
        )

    def _output_result(
        self,
        output: dict[str, Any],
        *,
        skill: VerifundSkill,
        task_id: str,
        run_id: str,
    ) -> VerifundTaskResult:
        interrupts = output.get("__interrupt__") or []
        if not interrupts:
            return self._completed_result(
                output, skill=skill, task_id=task_id, run_id=run_id
            )
        payload = interrupts[0].value
        reason = str(payload.get("reason"))
        checkpoint = PENDING_CHECKPOINTS.get(reason)
        if checkpoint is None:
            try:
                checkpoint = VerifundCheckpoint(reason)
            except ValueError:
                checkpoint = None
        if checkpoint is None:
            raise VerifundProtocolError(
                f"unknown lifecycle interrupt: {payload.get('reason')}"
            )
        return self._checkpoint_result(
            payload,
            checkpoint=checkpoint,
            skill=skill,
            task_id=task_id,
            run_id=run_id,
        )

    def _checkpoint_result(
        self,
        payload: dict[str, Any],
        *,
        checkpoint: VerifundCheckpoint,
        skill: VerifundSkill,
        task_id: str,
        run_id: str,
    ) -> VerifundTaskResult:
        common: dict[str, Any] = {
            "skill": skill,
            "task_id": task_id,
            "run_id": payload.get("run_id") or run_id,
            "transaction_id": payload.get("transaction_id"),
            "agreement_version": payload.get("agreement_version"),
            "agreement_hash": payload.get("agreement_hash"),
            "state": self._checkpoint_state(checkpoint, payload),
            "data": payload,
            "message": payload.get("message", ""),
        }
        if checkpoint is VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED:
            return VerifundTaskResult(
                **common,
                status="approval_required",
                checkpoint=checkpoint,
                approval_type="funding",
                next_action="approve_funding",
            )
        if checkpoint is VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED:
            return VerifundTaskResult(
                **common,
                status="approval_required",
                checkpoint=checkpoint,
                approval_type="release",
                next_action="approve_release",
            )
        if checkpoint is VerifundCheckpoint.PURCHASE_ORDER_REQUIRED:
            return VerifundTaskResult(
                **common,
                status="input_required",
                checkpoint=checkpoint,
                next_action="purchase_order",
            )
        if checkpoint in {
            VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
        }:
            return VerifundTaskResult(
                **common,
                status="input_required",
                checkpoint=checkpoint,
                next_action=(
                    "buyer_approval"
                    if checkpoint is VerifundCheckpoint.BUYER_APPROVAL_REQUIRED
                    else "seller_review"
                ),
            )
        return VerifundTaskResult(
            **common,
            status="completed",
            checkpoint=checkpoint,
            next_action=(
                "funding_settlement"
                if checkpoint is VerifundCheckpoint.FUNDING_PENDING
                else "evidence"
            ),
        )

    @staticmethod
    def _checkpoint_state(
        checkpoint: VerifundCheckpoint, payload: dict[str, Any]
    ) -> TransactionState:
        projection = payload.get("projection") or {}
        raw = projection.get("state")
        if raw:
            try:
                return TransactionState(raw)
            except ValueError:
                pass
        return CHECKPOINT_STATES[checkpoint]

    def _completed_result(
        self,
        values: dict[str, Any],
        *,
        skill: VerifundSkill,
        task_id: str,
        run_id: str,
    ) -> VerifundTaskResult:
        stage = str(values.get("stage") or "completed")
        receipt = values.get("receipt") or {}
        projection = values.get("release_projection") or {}
        if stage in {"rejected", "funding_rejected"}:
            state = TransactionState.CANCELED
            message = "The transaction was rejected; no funds moved."
        elif stage == "review_required":
            state = TransactionState.REVIEW_REQUIRED
            message = (
                "Release was not approved; the transaction is paused for "
                "manual review."
            )
        elif stage == "completed" and receipt.get("verified") is True:
            state = TransactionState.RELEASED
            message = "Transaction released; the verified receipt is attached."
        elif stage in {"released", "completed"}:
            state = TransactionState(
                str(projection.get("state") or TransactionState.PAYOUT_PENDING)
            )
            message = (
                "Transaction released; the receipt becomes available after "
                "the payout completes."
                if receipt is None
                else "Transaction released; receipt verification failed."
            )
        elif stage == "agreed":
            state = TransactionState.AGREED
            message = "Buyer and Seller agreed; funding is the next checkpoint."
        else:
            state = TransactionState.AWARDED
            message = f"Lifecycle stage {stage}."
        return VerifundTaskResult(
            skill=skill,
            status="completed",
            task_id=task_id,
            run_id=str(values.get("run_id") or run_id),
            transaction_id=values.get("transaction_id"),
            agreement_version=values.get("agreement_version"),
            agreement_hash=values.get("agreement_hash"),
            state=state,
            data={
                "stage": stage,
                "projection": values.get("projection"),
                "receipt": values.get("receipt"),
            },
            message=message,
        )

    def _failed(
        self,
        *,
        skill: VerifundSkill,
        task_id: str,
        run_id: str,
        message: str,
        retryable: bool = False,
    ) -> VerifundTaskResult:
        return VerifundTaskResult(
            skill=skill,
            status="failed",
            task_id=task_id,
            run_id=run_id or "unknown",
            message=message,
            retryable=retryable,
        )
