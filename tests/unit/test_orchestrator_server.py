from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from orchestrator_agent import server as server_module
from orchestrator_agent.settings import Settings
from orchestrator_agent.verifund import VerifundProtocolError

HASH = "a" * 64


class FakeLifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    async def resume_agreement(self, handle: Any, decision: Any) -> dict[str, Any]:
        self.calls.append((handle, decision))
        return {
            "status": "approval_required",
            "checkpoint": "funding_approval_required",
            "hitl": {
                "tool": "request_verifund_funding_approval",
                "args": {"run_id": handle.run_id},
            },
        }


class FailingLifecycle:
    async def resume_agreement(self, handle: Any, decision: Any) -> dict[str, Any]:
        raise VerifundProtocolError("agreement is not agreed")


def build_app(monkeypatch, lifecycle: Any):
    monkeypatch.setattr(server_module, "build_agent", lambda settings: object())
    monkeypatch.setattr(server_module, "ADKAgent", lambda **kwargs: object())
    monkeypatch.setattr(
        server_module, "add_adk_fastapi_endpoint", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        server_module,
        "build_verifund_lifecycle",
        lambda settings: lifecycle,
        raising=False,
    )
    return server_module.create_app(Settings(llm_mode="fake"))


def resume_body() -> dict[str, Any]:
    return {
        "task_id": "vf-task-1",
        "context_id": "vf-context-1",
        "run_id": "run-1",
        "decision": {
            "agreement_version": 1,
            "agreement_hash": HASH,
            "decision": "APPROVE",
            "note": "looks good",
            "idempotency_key": "buyer-decision:vf_1:1",
        },
    }


def test_resume_agreement_endpoint_resumes_the_verifund_handle(monkeypatch) -> None:
    lifecycle = FakeLifecycle()
    client = TestClient(build_app(monkeypatch, lifecycle))

    response = client.post("/verifund/resume-agreement", json=resume_body())

    assert response.status_code == 200
    assert response.json()["hitl"]["tool"] == "request_verifund_funding_approval"
    handle, decision = lifecycle.calls[0]
    assert handle.task_id == "vf-task-1"
    assert handle.context_id == "vf-context-1"
    assert handle.run_id == "run-1"
    assert decision.agreement_hash == HASH
    assert decision.decision.value == "APPROVE"


def test_resume_agreement_endpoint_reports_a_binding_error(monkeypatch) -> None:
    client = TestClient(build_app(monkeypatch, FailingLifecycle()))

    response = client.post("/verifund/resume-agreement", json=resume_body())

    assert response.status_code == 409
    assert response.json()["detail"] == "agreement is not agreed"


def test_resume_agreement_endpoint_rejects_an_unknown_decision(monkeypatch) -> None:
    client = TestClient(build_app(monkeypatch, FakeLifecycle()))
    body = resume_body()
    body["decision"]["decision"] = "MAYBE"

    response = client.post("/verifund/resume-agreement", json=body)

    assert response.status_code == 422
