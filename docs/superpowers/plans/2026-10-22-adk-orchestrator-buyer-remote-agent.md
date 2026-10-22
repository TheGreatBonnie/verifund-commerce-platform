# ADK Orchestrator with Buyer as Remote A2A Agent

## Goal

Move MarketMesh from the current "buyer is both commerce authority and AG-UI orchestrator" shape to the selected target architecture:

- A separate ADK orchestrator is the only AG-UI agent seen by the console.
- The buyer becomes an A2A remote agent, structurally similar to the seller agents.
- The buyer remains the commerce authority: discovery, RFQ, negotiation, ranking, approval handling, and order placement stay in the buyer graph.
- Approval becomes an A2A `input-required` flow rather than a LangGraph interrupt surfaced through AG-UI.
- The orchestrator may call the buyer and sellers directly through CopilotKit A2A middleware.
- Buyer and seller auth is intentionally omitted for the prototype; no bearer tokens are used for A2A calls.
- The migration is incremental: buyer A2A is added first, the console is switched second, and buyer AG-UI is removed only after A2A flows pass.

## Selected Decisions

| Decision | Selected |
|---|---|
| Orchestrator role | Delegates to buyer; buyer remains commerce authority |
| Buyer endpoint | A2A-only final state, with a temporary AG-UI compatibility window |
| Approval | A2A `input-required` |
| Delegation | Orchestrator calls buyer and sellers directly |
| Ranking/award | Buyer |
| Buyer auth | None for prototype |
| Migration scope | Incremental adapter |

## Non-Negotiables

- No Verifund code, services, environment variables, models, payment workflow, transaction coordinator, or dependencies.
- Prices, mandate checks, stock validation, ranking, and approval remain deterministic in the buyer.
- The buyer never reveals `max_total_cents` to sellers or the orchestrator prompt.
- Every order requires a human approval.
- Live Nebius behavior is optional; scripted buyer/seller behavior remains the deterministic default.
- Seller agent authentication is omitted for the prototype; no seller bearer tokens are used by the orchestrator.

## Target Topology

```text
Console (3000)
  -> CopilotKit runtime /api/copilotkit
     -> A2AMiddlewareAgent (a2a_chat)
        -> ADK orchestrator AG-UI (9000)
        -> MarketMesh Buyer A2A (9100/a2a)
        -> Northwind/CircuitForge/Aurora seller A2A (9201-9203/a2a)

ADK orchestrator (9000)
  -> ADK LlmAgent over Nebius OpenAI-compatible API
  -> AG-UI endpoint at /

MarketMesh Buyer (9100)
  -> /agui during compatibility window
  -> /a2a as the primary remote-agent endpoint
  -> LangGraph buyer graph
  -> buyer SQLite trace/checkpoint stores
  -> registry discovery
  -> seller A2A clients

Sellers (9201-9203)
  -> unchanged A2A endpoints
```

## A2A Message Contract

The buyer's A2A endpoint accepts one text part. The text may be plain text or JSON.

### Sourcing request

```json
{
  "brief": "Buy 12 Nimbus NC-700 ANC headsets..."
}
```

Plain text is also accepted and is treated as `brief`.

### Approval response

```json
{
  "approval": {
    "approved": true,
    "approved_by": "Demo Buyer",
    "note": "Approved after mandate review"
  },
  "task_id": "buyer-task-id-from-approval-required-response"
}
```

### Buyer response while approval is pending

```json
{
  "status": "approval_required",
  "task_id": "buyer-task-id",
  "message": "Human approval required before placing the order.",
  "award": { "...": "..." },
  "mandate": { "...": "..." }
}
```

### Buyer response after completion

```json
{
  "status": "ordered",
  "task_id": "buyer-task-id",
  "message": "Order confirmed.",
  "award": { "...": "..." },
  "order": { "...": "..." }
}
```

The orchestrator must preserve `task_id` from an `approval_required` response and include it in the approval message.

## Files to Add

- `apps/orchestrator_agent/orchestrator_agent/__init__.py`
- `apps/orchestrator_agent/orchestrator_agent/__main__.py`
- `apps/orchestrator_agent/orchestrator_agent/settings.py`
- `apps/orchestrator_agent/orchestrator_agent/agent.py`
- `apps/orchestrator_agent/orchestrator_agent/server.py`
- `apps/buyer_agent/buyer_agent/card.py`
- `apps/buyer_agent/buyer_agent/executor.py`
- `tests/protocol/test_buyer_a2a.py`
- `tests/unit/test_buyer_executor.py`

## Files to Modify

- `pyproject.toml`
- `apps/buyer_agent/buyer_agent/server.py`
- `apps/buyer_agent/buyer_agent/settings.py`
- `apps/buyer_agent/buyer_agent/__main__.py`
- `apps/console/app/api/copilotkit/[[...slug]]/route.ts`
- `apps/console/components/chat.tsx`
- `apps/console/components/console-shell.tsx`
- `scripts/config.py`
- `scripts/dev.py`
- `docker-compose.yml`
- `.env.example`
- `tests/protocol/conftest.py`
- `README.md` and `docs/architecture.md`

## Dependency Changes

Add to `pyproject.toml`:

```toml
"google-adk>=1.0,<2",
"ag-ui-adk>=0.1,<1",
"litellm>=1.84,<2",
```

Add `apps/orchestrator_agent` to `[tool.uv.workspace].members`.

The orchestrator uses Nebius through its OpenAI-compatible API. It does not introduce a new provider or a Verifund dependency.

## Phase 1: Add Buyer A2A Adapter

### Task 1.1: Buyer Agent Card

Create `apps/buyer_agent/buyer_agent/card.py`.

```python
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def build_buyer_agent_card(base_url: str) -> AgentCard:
    skills = [
        AgentSkill(
            id="commerce.sourcing",
            name="Source and negotiate",
            description="Discover sellers, negotiate offers, rank them, and prepare a human approval.",
            tags=["commerce", "sourcing", "negotiation"],
            input_modes=["application/json", "text/plain"],
            output_modes=["application/json", "text/plain"],
        ),
        AgentSkill(
            id="commerce.approval",
            name="Resume approved sourcing",
            description="Resume an interrupted sourcing run after a human approval decision.",
            tags=["commerce", "approval"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
    ]
    return AgentCard(
        name="MarketMesh Buyer",
        description="Commerce authority for MarketMesh sourcing runs.",
        version="1.0.0",
        provider=AgentProvider(organization="MarketMesh", url=base_url),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=skills,
    )
```

No security scheme is added. This is deliberate for the prototype and matches the selected "no buyer auth" decision.

### Task 1.2: Buyer Executor

Create `apps/buyer_agent/buyer_agent/executor.py`.

The executor must:

- Create or reuse a LangGraph thread using `context_id` or `task_id`.
- Parse the incoming A2A text as JSON when possible.
- Treat `{"brief": "..."}` or plain text as a new sourcing request.
- Treat `{"approval": {...}, "task_id": "..."}` as a resume of an interrupted graph.
- Invoke `buyer_agent.graph.build_buyer_graph`.
- Detect `__interrupt__` in the returned state.
- Enqueue `TASK_STATE_INPUT_REQUIRED` when approval is pending.
- Enqueue `TASK_STATE_COMPLETED` when the run finishes.
- Enqueue `TASK_STATE_FAILED` on exceptions.

Core implementation:

```python
import json
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from buyer_agent.approval import normalize_approval
from buyer_agent.graph import build_buyer_graph
from buyer_agent.planner import select_buyer_planner


class BuyerExecutor(AgentExecutor):
    def __init__(self, services, settings, checkpointer):
        self.services = services
        self.settings = settings
        self.planner = select_buyer_planner(
            settings.llm_mode,
            settings.nebius_api_key,
            settings.nebius_base_url,
            settings.nebius_model,
        )
        self.graph = build_buyer_graph(
            services=services,
            checkpointer=checkpointer,
            planner=self.planner,
        )

    def _text(self, message) -> str:
        if message is None:
            return ""
        for part in message.parts:
            if part.HasField("text") and part.text.strip():
                return part.text.strip()
        return ""

    def _payload(self, text: str) -> dict:
        if not text.startswith("{"):
            return {"brief": text}
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {"brief": text}
        if not isinstance(value, dict):
            return {"brief": text}
        return value

    async def execute(self, context, event_queue):
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        thread_id = context_id
        text = self._text(context.message)
        payload = self._payload(text)

        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
                history=[context.message] if context.message is not None else [],
            )
        )

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        task_id=task_id,
                        context_id=context_id,
                        role=Role.ROLE_AGENT,
                        parts=[Part(text="Buyer is evaluating the request.", media_type="text/plain")],
                    ),
                ),
            )
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "services": self.services,
                "planner": self.planner,
            }
        }

        try:
            if "approval" in payload and "task_id" in payload:
                thread_id = str(payload["task_id"])
                config["configurable"]["thread_id"] = thread_id
                decision = normalize_approval(payload["approval"])
                result = await self.graph.ainvoke(Command(resume=decision), config=config)
            else:
                brief = str(payload.get("brief") or text)
                result = await self.graph.ainvoke(
                    {"messages": [HumanMessage(content=brief)], "stage": "new"},
                    config=config,
                )
        except Exception as exc:  # noqa: BLE001
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=Message(
                            message_id=str(uuid.uuid4()),
                            task_id=task_id,
                            context_id=context_id,
                            role=Role.ROLE_AGENT,
                            parts=[Part(text=str(exc), media_type="text/plain")],
                        ),
                    ),
                )
            )
            return

        if "__interrupt__" in result:
            interrupt_value = result["__interrupt__"][0].value
            response = {
                "status": "approval_required",
                "task_id": thread_id,
                "message": interrupt_value.get("message", "Human approval required before placing the order."),
                "award": result.get("award"),
                "mandate": result.get("mandate"),
            }
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_INPUT_REQUIRED,
                        message=Message(
                            message_id=str(uuid.uuid4()),
                            task_id=task_id,
                            context_id=context_id,
                            role=Role.ROLE_AGENT,
                            parts=[Part(text=json.dumps(response), media_type="application/json")],
                        ),
                    ),
                )
            )
            return

        final_message = ""
        messages = result.get("messages", [])
        if messages:
            final_message = getattr(messages[-1], "content", "") or ""

        response = {
            "status": result.get("stage", "completed"),
            "task_id": thread_id,
            "message": final_message or "Buyer run completed.",
            "award": result.get("award"),
            "order": result.get("order"),
            "error": result.get("error"),
        }
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        task_id=task_id,
                        context_id=context_id,
                        role=Role.ROLE_AGENT,
                        parts=[Part(text=json.dumps(response), media_type="application/json")],
                    ),
                ),
            )
        )

    async def cancel(self, context, event_queue):
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_CANCELED,
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        task_id=task_id,
                        context_id=context_id,
                        role=Role.ROLE_AGENT,
                        parts=[Part(text="Buyer task canceled.", media_type="text/plain")],
                    ),
                ),
            )
        )
```

The buyer graph is not changed. The executor adapts its existing interrupt to A2A.

### Task 1.3: Wire Buyer A2A Routes

Modify `apps/buyer_agent/buyer_agent/server.py`.

Add imports:

```python
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import DatabaseTaskStore

from buyer_agent.card import build_buyer_agent_card
from buyer_agent.executor import BuyerExecutor
```

Inside `create_app`, after building `graph`:

```python
card = build_buyer_agent_card(settings.public_base_url)
task_store = DatabaseTaskStore(engine=engine, create_table=True)
executor = BuyerExecutor(
    services=services,
    settings=settings,
    checkpointer=checkpointer,
    graph=graph,
)
handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
    agent_card=card,
)
add_a2a_routes_to_fastapi(
    app,
    agent_card_routes=create_agent_card_routes(card),
    jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
)
```

Keep the existing `/agui` endpoint during the compatibility window. It will be removed in Phase 4.

### Task 1.4: Buyer Settings

Modify `apps/buyer_agent/buyer_agent/settings.py`.

Add:

```python
public_base_url: str = Field(
    default="http://127.0.0.1:9100",
    validation_alias=AliasChoices("BUYER_PUBLIC_BASE_URL", "PUBLIC_BASE_URL"),
)
```

Do not add a buyer token. The selected decision is no buyer auth for the prototype.

### Task 1.5: Buyer A2A Tests

Add `tests/unit/test_buyer_executor.py`.

Test cases:

1. Plain text is parsed as `{"brief": text}`.
2. JSON approval payload is parsed without changing `task_id`.
3. `normalize_approval` is called for approval payloads.
4. `__interrupt__` produces `TASK_STATE_INPUT_REQUIRED`.
5. Completed state produces `TASK_STATE_COMPLETED`.

Add `tests/protocol/test_buyer_a2a.py` with a `buyer_runtime` fixture. The fixture starts registry, all three sellers, and the buyer with `llm_mode="scripted"`. Test:

- `GET /.well-known/agent-card.json` returns name `MarketMesh Buyer`.
- `GET /health` returns `ok`.
- A sourcing brief returns JSON with `status == "approval_required"`.
- Sending the returned `task_id` with approval returns JSON with `status == "ordered"`.

The protocol test should use the real buyer graph and scripted sellers, not mocks.

## Phase 2: Add ADK Orchestrator

### Task 2.1: Create Orchestrator Package

Create `apps/orchestrator_agent/orchestrator_agent/settings.py`.

```python
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    service_name: str = "orchestrator"
    host: str = "127.0.0.1"
    port: int = Field(default=9000, validation_alias=AliasChoices("ORCHESTRATOR_PORT", "PORT"))
    orchestrator_url: str = "http://127.0.0.1:9000"
    buyer_a2a_url: str = "http://127.0.0.1:9100"
    seller_urls: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:9201",
            "http://127.0.0.1:9202",
            "http://127.0.0.1:9203",
        ],
        validation_alias=AliasChoices("SELLER_URLS", "ORCHESTRATOR_SELLER_URLS"),
    )

`seller_urls` has three entries because there are three independent seller services in the prototype: Northwind Audio, CircuitForge, and Aurora Supply. Each seller runs its own A2A JSON-RPC endpoint on a distinct port (`9201`, `9202`, and `9203`). The orchestrator uses these URLs to call sellers directly through A2A middleware, while the buyer still discovers sellers through the registry. The list is configuration, not a single seller with three endpoints.
    llm_mode: str = Field(default="live", validation_alias=AliasChoices("MARKETMESH_LLM_MODE", "LLM_MODE"))
    nebius_api_key: str | None = Field(default=None, validation_alias=AliasChoices("NEBIUS_API_KEY", "OPENAI_API_KEY"))
    nebius_base_url: str = Field(
        default="https://api.tokenfactory.us-central1.nebius.com/v1/",
        validation_alias=AliasChoices("NEBIUS_BASE_URL", "OPENAI_BASE_URL"),
    )
    nebius_model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash-0731",
        validation_alias=AliasChoices("NEBIUS_MODEL", "OPENAI_MODEL"),
    )
```

Create `apps/orchestrator_agent/orchestrator_agent/agent.py`.

```python
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from orchestrator_agent.settings import Settings


def build_agent(settings: Settings) -> LlmAgent:
    model = LiteLlm(
        model=f"openai/{settings.nebius_model}",
        api_base=settings.nebius_base_url,
        api_key=settings.nebius_api_key,
    )
    return LlmAgent(
        name="MarketMeshOrchestrator",
        model=model,
        instruction=(
            "You are the MarketMesh orchestrator. "
            "Use the MarketMesh Buyer A2A agent for sourcing, negotiation, ranking, and approval. "
            "Seller agents may be queried directly for status, but sourcing and award authority remain in the buyer. "
            "Never reveal or estimate the buyer's budget. "
            "When the buyer returns status approval_required, present the award and ask the user for approval. "
            "When the user approves, call MarketMesh Buyer again with JSON "
            "{\"approval\":{\"approved\":true,\"approved_by\":\"Demo Buyer\",\"note\":\"...\"},\"task_id\":\"...\"}. "
            "When the user rejects, call MarketMesh Buyer with approved set to false. "
            "Call agents one at a time and wait for each result."
        ),
    )
```

Create `apps/orchestrator_agent/orchestrator_agent/server.py`.

```python
from fastapi import FastAPI

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint

from orchestrator_agent.agent import build_agent
from orchestrator_agent.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    agent = build_agent(settings)
    adk_agent = ADKAgent(
        adk_agent=agent,
        app_name="marketmesh_orchestrator",
        user_id="demo_user",
        session_timeout_seconds=3600,
        use_in_memory_services=True,
    )
    app = FastAPI(title="MarketMesh Orchestrator")
    app.state.settings = settings
    add_adk_fastapi_endpoint(app, adk_agent, path="/")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestrator"}

    @app.get("/ready")
    async def ready():
        if settings.llm_mode == "live" and not settings.nebius_api_key:
            return {"status": "not_ready", "service": "orchestrator", "reason": "missing_api_key"}
        return {"status": "ready", "service": "orchestrator"}

    return app
```

Create `apps/orchestrator_agent/orchestrator_agent/__main__.py`.

```python
import uvicorn

from orchestrator_agent.server import create_app
from orchestrator_agent.settings import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
```

### Task 2.2: Orchestrator Tests

Add a lightweight settings test:

```python
def test_orchestrator_defaults():
    from orchestrator_agent.settings import Settings
    settings = Settings(ORCHESTRATOR_PORT=9010)
    assert settings.port == 9010
    assert settings.buyer_a2a_url == "http://127.0.0.1:9100"
```

Add a server smoke test that constructs the app and checks `/health`. The smoke test must not require a live API key.

## Phase 3: Switch Console to Orchestrator

### Task 3.1: Console Runtime Agent

Modify `apps/console/app/api/copilotkit/[[...slug]]/route.ts`.

Replace the buyer AG-UI URL with the orchestrator URL:

```ts
const orchestratorAguiUrl =
  process.env.ORCHESTRATOR_AGUI_URL ?? "http://127.0.0.1:9000";
```

Keep `a2a_chat` as the runtime agent ID. Update `agentUrls`:

```ts
agentUrls: [
  process.env.BUYER_A2A_URL ?? "http://127.0.0.1:9100",
  ...(process.env.SELLER_URLS?.split(",") ?? [
    "http://127.0.0.1:9201",
    "http://127.0.0.1:9202",
    "http://127.0.0.1:9203",
  ]),
],
```

Buyer and sellers have no auth token in the prototype. `BUYER_SELLER_TOKENS` is not used by the orchestrator.

### Task 3.2: Console State Adapter

The console currently reads buyer state from the AG-UI agent. After the switch, the Deal Room must be fed from buyer A2A results.

Modify `apps/console/components/console-shell.tsx`:

- Add local state `buyerState`.
- In the existing `useFrontendTool("send_message_to_a2a_agent")` render callback, parse JSON tool results whose `agentName === "MarketMesh Buyer"`.
- Update `buyerState` when a buyer result contains `status`, `award`, `mandate`, `order`, `error`, or `task_id`.
- Replace direct `agent.state` reads for Deal Room panels with `buyerState ?? {}`.
- Keep `agent.state` only for orchestrator chat status.

This keeps the visual Deal Room while the buyer is remote.

### Task 3.3: Approval UX

Approval is no longer a LangGraph interrupt. The orchestrator asks the user in chat and then calls the buyer with approval JSON.

Modify `apps/console/components/console-shell.tsx`:

- Remove `useInterrupt({ agentId: "a2a_chat", ... })` or convert it to a display-only component.
- Keep the approval card component, but drive it from `buyerState.status === "approval_required"`.
- Approval and rejection buttons should send a normal chat message containing the approval JSON and the buyer `task_id`. The orchestrator will then call the buyer.

This is less modal than before, but it matches the selected A2A `input-required` model.

### Task 3.4: Chat Labels

Update `apps/console/components/chat.tsx` labels from "Buyer agent · AG-UI" to "MarketMesh orchestrator · AG-UI" only if the UI text is user-visible. The runtime agent ID remains `a2a_chat`.

## Phase 4: Remove Buyer AG-UI

This phase starts only after Phase 1-3 tests pass.

### Task 4.1: Remove Buyer AG-UI Endpoint

Modify `apps/buyer_agent/buyer_agent/server.py`:

- Remove `add_langgraph_fastapi_endpoint`.
- Remove `LangGraphAgent` import.
- Keep `/a2a`, `/health`, `/ready`, metrics, and run APIs.
- Keep `console_api.router` for trace and run inspection.

### Task 4.2: Remove Buyer Direct AG-UI References

- Remove `BUYER_AGUI_URL` from console environment usage.
- Keep `BUYER_AGUI_URL` only if external tooling still needs it; otherwise remove from `.env.example`.
- Update `scripts/dev.py` to no longer wait for buyer `/agui`.
- Update docs to state that the buyer is A2A-only.

## Phase 5: Dev Stack, Docker, and Docs

### Task 5.1: Configuration Helpers

Modify `scripts/config.py`.

Add:

```python
def orchestrator_port() -> int:
    return int(os.environ.get("ORCHESTRATOR_PORT", "9000"))

def orchestrator_url() -> str:
    return os.environ.get("ORCHESTRATOR_URL", f"http://127.0.0.1:{orchestrator_port()}")

def orchestrator_agui_url() -> str:
    return os.environ.get("ORCHESTRATOR_AGUI_URL", orchestrator_url())

def buyer_a2a_url() -> str:
    return os.environ.get("BUYER_A2A_URL", buyer_url().replace("/agui", "") + "")
```

Use the existing buyer URL helper if it already returns the base URL. The important invariant is that the orchestrator receives the buyer base URL, not `/agui`.

### Task 5.2: Dev Stack

Modify `scripts/dev.py`.

Startup order:

1. registry
2. sellers
3. seed registry
4. buyer
5. orchestrator
6. console

Add `orchestrator_environment(mode)`:

```python
def orchestrator_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update({
        "PORT": str(orchestrator_port()),
        "ORCHESTRATOR_PORT": str(orchestrator_port()),
        "ORCHESTRATOR_URL": orchestrator_url(),
        "ORCHESTRATOR_AGUI_URL": orchestrator_agui_url(),
        "BUYER_A2A_URL": buyer_a2a_url(),
        "SELLER_URLS": ",".join(seller.base_url for seller in SELLERS),
        "COPILOTKIT_AGENT_MODEL": f"openai:{nebius_model()}",
        "OPENAI_BASE_URL": nebius_base_url(),
    })
    if mode == "live":
        env["OPENAI_API_KEY"] = nebius_api_key()
    return env
```

Console environment uses `ORCHESTRATOR_AGUI_URL`, not `BUYER_AGUI_URL`.

Wait for:

- buyer `/health`
- orchestrator `/health`
- console `/api/health` or root

### Task 5.3: Docker Compose

Add an `orchestrator` service:

```yaml
orchestrator:
  build:
    context: .
    dockerfile: apps/orchestrator_agent/Dockerfile
  environment:
    ORCHESTRATOR_PORT: "9000"
    BUYER_A2A_URL: "http://buyer:9100"
    SELLER_URLS: "http://northwind:9201,http://circuitforge:9202,http://aurora:9203"
    NEBIUS_API_KEY: "${NEBIUS_API_KEY}"
    NEBIUS_BASE_URL: "${NEBIUS_BASE_URL}"
    NEBIUS_MODEL: "${NEBIUS_MODEL}"
  depends_on:
    buyer:
      condition: service_healthy
```

Console environment:

```yaml
ORCHESTRATOR_AGUI_URL: "http://orchestrator:9000"
```

Buyer remains healthy on `/health`. Sellers remain unchanged.

### Task 5.4: Environment Example

Add:

```env
ORCHESTRATOR_PORT=9000
ORCHESTRATOR_URL=http://127.0.0.1:9000
ORCHESTRATOR_AGUI_URL=http://127.0.0.1:9000
BUYER_A2A_URL=http://127.0.0.1:9100
SELLER_URLS=http://127.0.0.1:9201,http://127.0.0.1:9202,http://127.0.0.1:9203
```

No seller token configuration is required for this prototype plan.

### Task 5.5: Documentation

Update `README.md` and `docs/architecture.md`:

- Orchestrator is the user-facing ADK agent.
- Buyer is an A2A remote agent.
- Buyer has no auth in the prototype.
- Approval is A2A `input-required`.
- Buyer AG-UI is compatibility-only during migration and is removed after validation.

## Phase 6: Validation

Run in this order:

```bash
uv lock
uv run ruff check .
uv run pytest -q
cd apps/console && npm run typecheck && npm run build
cd ../.. && docker compose config
uv run python scripts/dev.py --mode scripted
```

Playwright E2E:

```bash
cd apps/console && npx playwright test
```

Expected:

- 49+ Python tests pass before adding new tests.
- New buyer A2A tests pass.
- TypeScript and production build pass.
- Docker Compose config validates.
- Scripted E2E passes with a valid Nebius key for the orchestrator.
- Buyer A2A card is reachable at `http://127.0.0.1:9100/.well-known/agent-card.json`.
- Orchestrator is reachable at `http://127.0.0.1:9000/health`.
- A sourcing run reaches `approval_required`, then `ordered` after approval.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Buyer graph uses LangGraph interrupt semantics that do not map directly to A2A | Executor detects `__interrupt__` and maps it to `TASK_STATE_INPUT_REQUIRED`; approval resumes with `Command(resume=...)` |
| A2A follow-up messages do not preserve task/context IDs | Approval JSON includes the buyer `task_id` from the pending response |
| Console Deal Room depends on buyer AG-UI state | Add a state adapter that reads buyer A2A JSON results; keep AG-UI until that adapter is validated |
| Orchestrator requires an LLM even in scripted mode | Document that scripted mode scripts buyer/seller behavior only; orchestrator uses Nebius/OpenAI-compatible API |
| Buyer no-auth endpoint could be mistaken for production-ready | Docs and settings comments state that buyer auth is intentionally omitted only for the prototype |
| Removing AG-UI too early breaks trace inspection | Keep buyer trace and run APIs after AG-UI removal |

## Definition of Done

The migration is complete when:

1. The ADK orchestrator is the only AG-UI agent used by the console.
2. The buyer exposes a working A2A endpoint and card.
3. A sourcing run can be started, negotiated, approved, and ordered through the orchestrator and buyer A2A.
4. Approval is represented as A2A `input-required`.
5. Buyer AG-UI is removed.
6. Ruff, Python tests, TypeScript checks, console build, Docker Compose validation, and Playwright E2E pass.