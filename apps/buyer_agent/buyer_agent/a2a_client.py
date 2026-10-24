from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

import httpx
from a2a.client import Client, ClientConfig, ClientFactory
from a2a.types.a2a_pb2 import (
    CancelTaskRequest,
    Message,
    Role,
    SendMessageRequest,
    StreamResponse,
    TaskState,
)
from commerce_core.a2a_parts import make_message, part_value
from commerce_core.contracts import (
    RFQ,
    AcceptOffer,
    CommerceError,
    CounterOffer,
    Offer,
    Order,
    PurchaseOrderRequest,
)
from commerce_core.extension import SCHEMA_FILES, parse_payload, wrap_payload

from buyer_agent.registry_client import SellerEndpoint
from buyer_agent.trace import TraceStore


def create_client(card, config: ClientConfig) -> Client:
    return ClientFactory(config).create(card)


def _schema_kind(value: dict) -> str | None:
    schema = value.get("schema", "")
    for kind, filename in SCHEMA_FILES.items():
        if schema.endswith(f"/{filename}"):
            return kind
    return None


@dataclass
class A2ATurn:
    task_id: str | None
    context_id: str | None
    state: TaskState
    offers: list[Offer] = field(default_factory=list)
    order: Order | None = None
    error: CommerceError | None = None
    text: str = ""

    @classmethod
    def from_frames(
        cls, frames: list[StreamResponse], endpoint: SellerEndpoint
    ) -> A2ATurn:
        task_id = None
        context_id = None
        state = TaskState.TASK_STATE_UNSPECIFIED
        offers: list[Offer] = []
        order = None
        error = None
        texts: list[str] = []

        def capture_message(message: Message) -> None:
            for part in message.parts:
                if part.HasField("text") and part.text:
                    texts.append(part.text)

        for frame in frames:
            kind = frame.WhichOneof("payload")
            if kind == "task":
                task = frame.task
                task_id = task.id
                context_id = task.context_id
                state = task.status.state
                capture_message(task.status.message)
                for artifact in task.artifacts:
                    _parse_artifact(
                        artifact, endpoint, offers
                    )
            elif kind == "status_update":
                update = frame.status_update
                task_id = update.task_id
                context_id = update.context_id
                state = update.status.state
                capture_message(update.status.message)
            elif kind == "artifact_update":
                update = frame.artifact_update
                task_id = update.task_id
                context_id = update.context_id
                parsed = _artifact_payload(update.artifact)
                if parsed:
                    kind_name = _schema_kind(parsed)
                    if kind_name == "offer":
                        offers.append(
                            _apply_endpoint_metadata(
                                parse_payload("offer", parsed, Offer),
                                endpoint,
                            )
                        )
                    elif kind_name == "order":
                        order = parse_payload("order", parsed, Order)
                    elif kind_name == "commerce_error":
                        error = parse_payload(
                            "commerce_error", parsed, CommerceError
                        )
            elif kind == "message":
                capture_message(frame.message)
        return cls(
            task_id=task_id,
            context_id=context_id,
            state=state,
            offers=offers,
            order=order,
            error=error,
            text=" ".join(texts).strip(),
        )


def _artifact_payload(artifact) -> dict | None:
    for part in artifact.parts:
        value = part_value(part)
        if value is not None:
            return value
    return None


def _parse_artifact(artifact, endpoint, offers: list[Offer]) -> None:
    payload = _artifact_payload(artifact)
    if not payload or _schema_kind(payload) != "offer":
        return
    offers.append(
        _apply_endpoint_metadata(
            parse_payload("offer", payload, Offer), endpoint
        )
    )


def _apply_endpoint_metadata(offer: Offer, endpoint: SellerEndpoint) -> Offer:
    return offer.model_copy(
        update={
            "seller_rating": endpoint.rating,
            "terms": offer.terms.model_copy(
                update={
                    "sustainability_certified": (
                        endpoint.sustainability_certified
                    )
                }
            ),
        }
    )


class A2ASellerSession:
    def __init__(
        self,
        endpoint: SellerEndpoint,
        trace: TraceStore,
        run_id: str,
    ) -> None:
        self.endpoint = endpoint
        self.trace = trace
        self.run_id = run_id
        self.http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {endpoint.token}"},
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        self.client: Client | None = None

    async def open(self) -> A2ASellerSession:
        self.client = create_client(
            self.endpoint.card,
            ClientConfig(streaming=True, httpx_client=self.http),
        )
        return self

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
        await self.http.aclose()

    async def send(self, message: Message) -> A2ATurn:
        if self.client is None:
            raise RuntimeError("A2A session is not open")
        frames: list[StreamResponse] = []
        await self.trace.record_message(
            self.run_id, self.endpoint.seller_id, message
        )
        started = perf_counter()
        async for event in self.client.send_message(
            SendMessageRequest(message=message)
        ):
            frames.append(event)
            await self.trace.record_frame(
                self.run_id,
                self.endpoint.seller_id,
                event,
                latency_ms=int((perf_counter() - started) * 1000),
            )
        return A2ATurn.from_frames(frames, self.endpoint)

    async def send_rfq(self, rfq: RFQ, context_id: str) -> A2ATurn:
        return await self.send(
            make_message(
                role=Role.ROLE_USER,
                text="Requesting a quote.",
                context_id=context_id,
                envelope=wrap_payload("rfq", rfq),
            )
        )

    async def send_counter(
        self, task_id: str, context_id: str, counter: CounterOffer
    ) -> A2ATurn:
        return await self.send(
            make_message(
                role=Role.ROLE_USER,
                text="Counteroffer.",
                context_id=context_id,
                task_id=task_id,
                envelope=wrap_payload("counter_offer", counter),
            )
        )

    async def send_accept(
        self, task_id: str, context_id: str, accept: AcceptOffer
    ) -> A2ATurn:
        return await self.send(
            make_message(
                role=Role.ROLE_USER,
                text="Accepting the offer.",
                context_id=context_id,
                task_id=task_id,
                envelope=wrap_payload("accept_offer", accept),
            )
        )

    async def send_order(
        self, po: PurchaseOrderRequest, context_id: str
    ) -> A2ATurn:
        return await self.send(
            make_message(
                role=Role.ROLE_USER,
                text="Human-approved purchase order.",
                context_id=context_id,
                envelope=wrap_payload("purchase_order", po),
            )
        )

    async def cancel(self, task_id: str):
        if self.client is None:
            raise RuntimeError("A2A session is not open")
        return await self.client.cancel_task(
            CancelTaskRequest(id=task_id)
        )


class SellerA2AClient:
    """Factory for authenticated A2A sessions to independently operated sellers."""

    def __init__(self, trace: TraceStore) -> None:
        self.trace = trace

    async def open_session(
        self, endpoint: SellerEndpoint, run_id: str
    ) -> A2ASellerSession:
        return await A2ASellerSession(endpoint, self.trace, run_id).open()
