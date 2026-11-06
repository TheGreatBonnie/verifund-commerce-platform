from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from verifund_control_plane.agents.credentials import issue_credential, verify_credential
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import require_identity

router = APIRouter()


class VerifyRequest(BaseModel):
    token: str = Field(min_length=1)


class IssueRequest(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["a2a:call"])


@router.post("/v1/agent-credentials/verify")
async def verify(request: Request, body: VerifyRequest) -> dict:
    return await verify_credential(request.app.state.tenancy, body.token)


@router.post("/v1/agents/{agent_id}/credentials", status_code=201)
async def issue(request: Request, agent_id: str, body: IssueRequest) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    agent = await store.get_agent(agent_id)
    if agent is None or agent["organization_id"] != identity.tenant_id:
        raise VerifundError("not_found", "agent not found", status_code=404)
    raw = await issue_credential(store, identity.tenant_id, agent_id, body.scopes)
    return {"credential": raw}
