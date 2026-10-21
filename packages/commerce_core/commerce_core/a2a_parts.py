import uuid

from a2a.types.a2a_pb2 import Artifact, Message, Part, Role
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Value


def data_part(envelope: dict) -> Part:
    value = Value()
    json_format.ParseDict(envelope, value)
    return Part(data=value, media_type="application/json")


def part_value(part: Part) -> dict | None:
    if not part.HasField("data"):
        return None
    return json_format.MessageToDict(part.data)


def make_artifact(name: str, envelope: dict) -> Artifact:
    return Artifact(
        artifact_id=str(uuid.uuid4()),
        name=name,
        parts=[data_part(envelope)],
    )


def make_message(
    *,
    role: Role,
    text: str,
    context_id: str,
    task_id: str | None = None,
    envelope: dict | None = None,
    reference_task_ids: list[str] | None = None,
) -> Message:
    parts = [Part(text=text, media_type="text/plain")]
    if envelope is not None:
        parts.append(data_part(envelope))
    return Message(
        message_id=str(uuid.uuid4()),
        role=role,
        context_id=context_id,
        task_id=task_id or "",
        parts=parts,
        reference_task_ids=reference_task_ids or [],
    )


def first_envelope(message: Message) -> dict | None:
    for part in message.parts:
        value = part_value(part)
        if value is not None:
            return value
    return None
