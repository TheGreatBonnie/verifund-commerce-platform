from __future__ import annotations

from a2a.client import ClientConfig, ClientFactory
from a2a.client.auth.credentials import CredentialService
from a2a.client.auth.interceptor import AuthInterceptor
from a2a.client.client import Client, ClientCallContext
from a2a.types.a2a_pb2 import (
    Role,
    SendMessageRequest,
    StreamResponse,
    TaskState,
)
from commerce_core.a2a_parts import make_message, part_value
from commerce_core.extension import SCHEMA_FILES, wrap_payload


class StaticCredentialService(CredentialService):
    def __init__(self, token: str) -> None:
        self.token = token

    async def get_credentials(
        self, security_scheme_name: str, context: ClientCallContext | None
    ) -> str | None:
        return self.token


async def make_client(card, token: str) -> Client:
    factory = ClientFactory(ClientConfig(streaming=True))
    return factory.create(card, [AuthInterceptor(StaticCredentialService(token))])


async def collect_stream(
    client: Client, request: SendMessageRequest
) -> list[StreamResponse]:
    return [event async for event in client.send_message(request)]


def event_kind(event: StreamResponse) -> str:
    return event.WhichOneof("payload") or ""


def first_task_id(events: list[StreamResponse]) -> str:
    for event in events:
        if event_kind(event) == "task":
            return event.task.id
        if event_kind(event) == "status_update":
            return event.status_update.task_id
        if event_kind(event) == "artifact_update":
            return event.artifact_update.task_id
    raise AssertionError("no task id in events")


def task_state(events: list[StreamResponse]) -> TaskState:
    state = TaskState.TASK_STATE_UNSPECIFIED
    for event in events:
        if event_kind(event) == "task":
            state = event.task.status.state
        elif event_kind(event) == "status_update":
            state = event.status_update.status.state
    return state


def last_offer(events: list[StreamResponse]) -> dict:
    found = None
    for event in events:
        if event_kind(event) != "artifact_update":
            continue
        artifact = event.artifact_update.artifact
        for part in artifact.parts:
            value = part_value(part)
            if value and value.get("schema", "").endswith(
                f"/{SCHEMA_FILES['offer']}"
            ):
                found = value["payload"]
    assert found is not None, "no offer artifact"
    return found


def last_error(events: list[StreamResponse]) -> dict:
    found = None
    for event in events:
        if event_kind(event) != "artifact_update":
            continue
        artifact = event.artifact_update.artifact
        for part in artifact.parts:
            value = part_value(part)
            if value and value.get("schema", "").endswith(
                f"/{SCHEMA_FILES['commerce_error']}"
            ):
                found = value["payload"]
    assert found is not None, "no commerce-error artifact"
    return found


def last_order(events: list[StreamResponse]) -> dict:
    found = None
    for event in events:
        if event_kind(event) != "artifact_update":
            continue
        artifact = event.artifact_update.artifact
        for part in artifact.parts:
            value = part_value(part)
            if value and value.get("schema", "").endswith(
                f"/{SCHEMA_FILES['order']}"
            ):
                found = value["payload"]
    assert found is not None, "no order artifact"
    return found


async def send_purchase_order(session, po, *, context_id: str = "order-run"):
    message = make_message(
        role=Role.ROLE_USER,
        text="Human-approved purchase order.",
        context_id=context_id,
        envelope=wrap_payload("purchase_order", po),
    )
    events = await collect_stream(
        session.client, SendMessageRequest(message=message)
    )
    try:
        return last_order(events)
    except AssertionError:
        return last_error(events)
