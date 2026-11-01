from __future__ import annotations

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from fastapi import FastAPI, HTTPException
from google.adk.sessions import DatabaseSessionService
from pydantic import BaseModel
from verifund_contracts import BuyerAgreementApprovalDecision

from orchestrator_agent.agent import build_agent, build_verifund_lifecycle
from orchestrator_agent.settings import Settings
from orchestrator_agent.verifund import VerifundProtocolError, VerifundTaskHandle


class ResumeAgreementRequest(BaseModel):
    task_id: str
    context_id: str
    run_id: str
    decision: BuyerAgreementApprovalDecision


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    agent = build_agent(settings)
    session_service = DatabaseSessionService(settings.session_db_url)
    adk_agent = ADKAgent(
        adk_agent=agent,
        app_name="marketmesh_orchestrator",
        user_id="demo_user",
        session_timeout_seconds=30 * 24 * 3600,
        use_in_memory_services=True,
        session_service=session_service,
        use_thread_id_as_session_id=True,
        delete_session_on_cleanup=False,
        save_session_to_memory_on_cleanup=False,
    )
    app = FastAPI(title="MarketMesh Orchestrator")
    app.state.settings = settings
    app.state.adk_agent = adk_agent
    add_adk_fastapi_endpoint(app, adk_agent, path="/")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "orchestrator"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        if settings.llm_mode == "live" and not settings.nebius_api_key:
            return {"status": "not_ready", "service": "orchestrator", "reason": "missing_api_key"}
        return {"status": "ready", "service": "orchestrator"}

    @app.post("/verifund/resume-agreement")
    async def resume_agreement(body: ResumeAgreementRequest) -> dict:
        lifecycle = build_verifund_lifecycle(settings)
        try:
            return await lifecycle.resume_agreement(
                VerifundTaskHandle(
                    body.task_id, body.context_id, body.run_id
                ),
                body.decision,
            )
        except VerifundProtocolError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
