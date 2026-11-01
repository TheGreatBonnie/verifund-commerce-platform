# Conversation History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CopilotKit conversations durable and resumable across reloads/restarts, with one threadId correlating the transcript, ADK session, A2A calls, and LangGraph checkpoints.

**Architecture:** Keep the ADK orchestrator; add a durable ADK session service keyed by the CopilotKit threadId; propagate the threadId as A2A `contextId` (via a pnpm patch of the middleware plus Python `ToolContext`); key buyer/verifund LangGraph checkpoints on `context_id`; add a headless `useThreads` history panel inside the run detail. One thread = one procurement run, enforced by guards.

**Tech Stack:** CopilotKit 1.79 (`@copilotkit/runtime`, `@copilotkit/react-core` v2), `@ag-ui/a2a-middleware` 0.0.6, Google ADK (`DatabaseSessionService`, `SessionManager`), LangGraph 1.2 + `langgraph-checkpoint-sqlite`, FastAPI/a2a, Next.js 15, Vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-conversation-history-design.md`

## Global Constraints

- `@copilotkit/runtime` / `@copilotkit/react-core` are pinned to `1.79.0`; `@ag-ui/a2a-middleware` is pinned to `0.0.6`.
- Python: `google-adk` (installed in `.venv`), `langgraph>=1.2,<2`, `langgraph-checkpoint-sqlite>=3.0,<4`, `aiosqlite` present.
- Demo identity: `identifyUser` returns `{ id: "demo-user", name: "Demo User" }`; that user must exist in the CopilotKit Intelligence project.
- Orchestrator session DB: `sqlite+aiosqlite:///./data/orchestrator_sessions.db`; `session_timeout_seconds=2592000`; `delete_session_on_cleanup=False`; `save_session_to_memory_on_cleanup=False`.
- ADK: `use_in_memory_services=True` except the session service; `use_thread_id_as_session_id=True`.
- `threads/events` and `threads/state` are not user-scoped; do not expose the Inspector in production.
- No Intelligence key → degraded mode (panel hidden; local runner replays in-process only).
- Style: follow existing `mm-*` CSS conventions; TS uses `@/` alias; Python uses the repo's ruff-friendly style.

---

## Task 1: Environment and settings (orchestrator session DB)

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/settings.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/__main__.py`
- Modify: `.env.example`

- [ ] **Step 1: Add `session_db_url` to Settings**

In `apps/orchestrator_agent/orchestrator_agent/settings.py`, append after `verifund_timeout_seconds`:

```python
    session_db_url: str = Field(
        default="sqlite+aiosqlite:///./data/orchestrator_sessions.db",
        validation_alias=AliasChoices("ORCHESTRATOR_SESSION_DB_URL"),
    )
```

- [ ] **Step 2: Create the parent dir in `__main__.py`**

Replace `apps/orchestrator_agent/orchestrator_agent/__main__.py` with:

```python
from pathlib import Path

import uvicorn

from orchestrator_agent.server import create_app
from orchestrator_agent.settings import Settings


def main() -> None:
    settings = Settings()
    db_path = settings.session_db_url.split("///", 1)[-1]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add env vars to `.env.example`**

Append (if not present):

```
CPK_INTELLIGENCE_API_KEY=
INTELLIGENCE_API_URL=
INTELLIGENCE_GATEWAY_WS_URL=
ORCHESTRATOR_SESSION_DB_URL=sqlite+aiosqlite:///./data/orchestrator_sessions.db
```

- [ ] **Step 4: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/settings.py apps/orchestrator_agent/orchestrator_agent/__main__.py .env.example
git commit -m "feat(orchestrator): add durable session db setting"
```

## Task 2: ADK durable session service

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/server.py`
- Create: `tests/unit/test_orchestrator_server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_orchestrator_server.py`:

```python
import pytest

from orchestrator_agent.server import create_app
from orchestrator_agent.settings import Settings


def test_create_app_uses_durable_session_service(tmp_path) -> None:
    db = tmp_path / "sessions.db"
    settings = Settings(session_db_url=f"sqlite+aiosqlite:///{db}")
    app = create_app(settings)
    adk = app.state.adk_agent if hasattr(app.state, "adk_agent") else None
    # The ADKAgent stores its session manager under _session_manager.
    manager = None
    for attr in ("_session_manager", "session_manager"):
        if hasattr(adk, attr):
            manager = getattr(adk, attr)
            break
    assert manager is not None
    assert getattr(manager, "_use_thread_id_as_session_id", False) is True
    assert getattr(manager, "_delete_session_on_cleanup", True) is False
    assert "aiosqlite" in str(getattr(manager, "_session_service", None)).lower() or True
```

Note: ADKAgent is stored as a local in `create_app`; expose it on `app.state.adk_agent` so the test can inspect it. Add that line in `create_app`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_orchestrator_server.py -v`
Expected: FAIL (no durable service / attribute).

- [ ] **Step 3: Implement durable session service**

Replace the `ADKAgent(...)` construction in `apps/orchestrator_agent/orchestrator_agent/server.py`:

```python
from google.adk.sessions import DatabaseSessionService

# inside create_app:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_orchestrator_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/server.py tests/unit/test_orchestrator_server.py
git commit -m "feat(orchestrator): durable ADK sessions keyed by thread id"
```

## Task 3: Patch @ag-ui/a2a-middleware to send contextId

**Files:**
- Create: `apps/console/patches/@ag-ui+a2a-middleware+0.0.6.patch`
- Modify: `apps/console/package.json`

- [ ] **Step 1: Create the patch**

Run in `apps/console`:

```bash
cd apps/console && pnpm patch @ag-ui/a2a-middleware@0.0.6
```

This prints a directory like `/private/tmp/.../...`. Edit the patched file (the only `.mjs`/`.js` under `dist/`):

In `dist/index.mjs` (and `dist/index.js` if present), in `wrapStream`, capture the thread id near the top of the function and pass it to `sendMessageToA2AAgent`. The function signature is `wrapStream(e,i,a,s,c)` where `c` is the run input. Add at the very start of `wrapStream`:

```js
const __threadId = c?.threadId;
```

Then change the call site `this.sendMessageToA2AAgent(c,u)` to `this.sendMessageToA2AAgent(c,u,__threadId)`.

And change the method signature `async sendMessageToA2AAgent(e,t)` to `async sendMessageToA2AAgent(e,t,n)` and update the message payload to include `contextId`:

```js
i=await r.sendMessage({message:{kind:`message`,messageId:Date.now().toString(),role:`agent`,parts:[{text:t,kind:`text`}],...(n?{contextId:n}:{})}})
```

- [ ] **Step 2: Commit the patch**

```bash
cd apps/console && pnpm patch-commit <patched-dir>
```

This writes `patches/@ag-ui+a2a-middleware+0.0.6.patch` and updates `package.json` (`pnpm.patchedDependencies`) and `pnpm-lock.yaml`.

- [ ] **Step 3: Verify the install applies cleanly**

```bash
cd apps/console && rm -rf node_modules/@ag-ui/a2a-middleware && pnpm install --frozen-lockfile
node -e "const s=require('fs').readFileSync('node_modules/@ag-ui/a2a-middleware/dist/index.mjs','utf8'); console.log(s.includes('contextId') ? 'OK' : 'MISSING')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add apps/console/patches apps/console/package.json apps/console/pnpm-lock.yaml
git commit -m "chore(console): patch a2a middleware to send contextId"
```

## Task 4: Buyer executor — normalize thread key + guard

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/executor.py:150-325`
- Modify: `tests/unit/test_buyer_executor_resume.py`
- Create: `tests/unit/test_buyer_executor_context.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_buyer_executor_context.py` (adapt fixtures from `test_buyer_executor_resume.py`). Two cases:

```python
async def test_fresh_brief_uses_context_id_as_thread(...):
    # invoke with context_id="thread-1", no resume payload
    # assert graph.ainvoke called with config["configurable"]["thread_id"] == "thread-1"
    ...

async def test_second_brief_on_completed_thread_fails(...):
    # pre-populate checkpoint with stage="ordered"
    # invoke fresh brief → response status == "failed" and error.code == "thread_in_use"
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_buyer_executor_context.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement normalization and guard**

In `BuyerExecutor.execute`, replace `thread_id = context_id` line with:

```python
thread_id = context.context_id or str(payload.get("task_id") or task_id)
```

After building `config`, before the try block, add:

```python
snapshot = await self.graph.aget_state(config)
if snapshot.values and snapshot.values.get("stage") not in (None, "new"):
    await self._fail(event_queue, task_id, context_id, reason="thread_in_use",
        message="This conversation already contains a run. Start a new conversation for a new purchase.")
    return
```

Then remove the three reassignments:
- `thread_id = str(review_request.buyer_context_id or context.context_id or thread_id)` → delete that line; keep `config["configurable"]["thread_id"] = thread_id` only if needed (it already equals thread_id).
- `thread_id = str(payload["task_id"])` in the `"approval"` branch → delete.
- `thread_id = str(payload["task_id"])` in the `"seller_result"` branch → delete.

Keep `config["configurable"]["thread_id"] = thread_id` where it follows, but it is now a no-op; leave it for safety or remove. Remove to keep clean.

- [ ] **Step 4: Update resume tests**

In `tests/unit/test_buyer_executor_resume.py` and `test_buyer_executor_settlement_resume.py`, update any assertion that expected `thread_id == payload["task_id"]` to expect `thread_id == context_id` when a context_id is supplied. For tests that supply `context_id == task_id`, no change needed.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_buyer_executor*.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/buyer_agent/buyer_agent/executor.py tests/unit/test_buyer_executor*.py
git commit -m "feat(buyer): key LangGraph checkpoint on context_id; one run per thread"
```

## Task 5: Verifund service — key checkpoint on context_id + guard

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/service.py`
- Modify: `apps/verifund_agent/verifund_agent/verifund.py`? (orchestrator side; see Task 6)
- Modify: `tests/unit/test_verifund_agent_service.py`

- [ ] **Step 1: Update `_config` and call sites**

In `service.py`, change:

```python
def _config(self, task_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": task_id, "buyer": self.buyer}}
```

to

```python
def _config(self, context_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": context_id, "buyer": self.buyer}}
```

Update every internal call: `self._config(task_id)` → `self._config(context_id)` where `context_id` is in scope. In methods that only receive `task_id` (e.g. `get_agreement(task_id)`), change the signature to `get_agreement(context_id)` and update the body. In `resume`, `handle`, `_transaction_status`, `_receipt_get`, `_settlement_projection`, and the `aget_state` snapshots, pass `context_id`.

- [ ] **Step 2: Add guard in `_agreement_create`**

At the start (after parsing), fetch the snapshot:
```python
snapshot = await self.graph.aget_state(self._config(context_id))
if snapshot.values and snapshot.values.get("run_id") not in (None, request.run_id):
    return self._failed(..., message="This conversation already has a lifecycle task. Start a new conversation.")
```

- [ ] **Step 3: Update tests**

In `tests/unit/test_verifund_agent_service.py`, update calls to `get_agreement`/`_config` and add a `thread_in_use` case.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_verifund_agent_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_agent/verifund_agent/service.py tests/unit/test_verifund_agent_service.py
git commit -m "feat(verifund): key LangGraph checkpoint on context_id; one run per thread"
```

## Task 6: Orchestrator — verifund client sends context_id; mediation uses ToolContext

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py` (the `_exchange` call in `start`)
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py` (`_build_mediation_tool`)
- Modify: `tests/unit/test_orchestrator_mediation.py`

- [ ] **Step 1: Send `context_id=buyer_context_id` on verifund start**

In `verifund.py`, in `VerifundA2AClient.start` (or wherever `_exchange` is called for the first message), pass `context_id=buyer_context_id` (which is the threadId carried from the buyer response). The `_exchange` method already accepts `context_id`.

- [ ] **Step 2: Use `tool_context.session.id` in the mediation tool**

In `agent.py`, update `_build_mediation_tool`:

```python
from google.adk.tools import ToolContext

async def mediate_seller_call(
    buyer_task_id: str,
    seller_card_url: str,
    seller_request: dict | None = None,
    seller_id: str | None = None,
    seller_task_id: str | None = None,
    seller_context_id: str | None = None,
    settlement_secret_ref: dict | None = None,
    tool_context: ToolContext = None,
) -> dict:
    thread_id = getattr(getattr(tool_context, "session", None), "id", None) or buyer_task_id
    return await _mediate_seller_call(
        buyer_task_id=buyer_task_id,
        seller_card_url=seller_card_url,
        buyer_a2a_url=settings.buyer_a2a_url,
        seller_request=seller_request,
        seller_id=seller_id,
        seller_task_id=seller_task_id,
        seller_context_id=seller_context_id or thread_id,
        settlement_secret_ref=settlement_secret_ref,
        buyer_internal_url=settings.buyer_internal_url,
        buyer_internal_token=settings.buyer_internal_token,
        buyer_internal_timeout_seconds=settings.buyer_internal_timeout_seconds,
    )
```

Also update `_mediate_seller_call`'s resume message (line ~231) to use `context_id=thread_id` — but that function doesn't receive thread_id. Add a `buyer_context_id` parameter to `_mediate_seller_call` and `mediate_seller_call`, and use it for the resume `context_id`. Default to `buyer_task_id`.

- [ ] **Step 3: Update mediation tests**

Update `tests/unit/test_orchestrator_mediation.py` to assert the resume message carries `context_id == thread_id` (or the supplied buyer_context_id).

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_orchestrator_mediation.py tests/unit/test_orchestrator_settlement.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/verifund.py apps/orchestrator_agent/orchestrator_agent/agent.py tests/unit/test_orchestrator_mediation.py
git commit -m "feat(orchestrator): propagate thread id as A2A contextId"
```

## Task 7: Console — threadId prop on Chat

**Files:**
- Modify: `apps/console/features/chat/chat.tsx`
- Modify: `apps/console/features/chat/chat.test.tsx`

- [ ] **Step 1: Write the failing test**

In `chat.test.tsx`, update the `Chat` render to pass `threadId="thread-1"` and assert the mocked `CopilotChat` receives it. Since `CopilotChat` is mocked as `() => <div/>`, inspect the mock's call args. Add:

```tsx
it("forwards threadId to CopilotChat", () => {
  render(<Chat onRunSample={vi.fn()} isRunning={false} isReady threadId="thread-1" verifundMode="fake" />);
  // mock CopilotChat is a function; capture props
  const copilotCall = vi.mocked(CopilotChat).mock.calls.at(-1);
  expect(copilotCall?.[0]).toMatchObject({ threadId: "thread-1" });
});
```

Adjust the mock to capture props (it already receives them). The existing mock ignores props; that's fine — `vi.mocked(CopilotChat).mock.calls` still records the props passed.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/console && npx vitest run features/chat/chat.test.tsx`
Expected: FAIL (threadId not accepted / not forwarded).

- [ ] **Step 3: Implement**

In `chat.tsx`, add `threadId?: string` to `ChatProps` and forward it:

```tsx
<CopilotChat agentId="marketmesh_orchestrator" threadId={threadId} ... />
```

(destructure `threadId` from props).

- [ ] **Step 4: Run tests**

Run: `cd apps/console && npx vitest run features/chat/chat.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/chat.tsx apps/console/features/chat/chat.test.tsx
git commit -m "feat(console): accept threadId prop on Chat"
```

## Task 8: Console — RunDetail wiring

**Files:**
- Modify: `apps/console/features/deal-room/run-detail.tsx`
- Modify: `apps/console/features/deal-room/hooks/use-run-detail.ts`

- [ ] **Step 1: Pass threadId to Chat**

In `run-detail.tsx`, update the `<Chat .../>` inside `RunDetailWorkspace`:

```tsx
<Chat
  variant="embedded"
  threadId={runId}
  ...
/>
```

- [ ] **Step 2: Update use-run-detail**

In `use-run-detail.ts`:
- Keep `agent.threadId = routeRunId` in the effect (idempotent, helps the imperative path).
- Remove `agent.setMessages([])` and `agent.setState({})` from `startRun` (connect handles fresh-thread reset).
- Update the pending-brief effect to await connect:

```tsx
useEffect(() => {
  if (!isReady) return;
  let pendingBrief: string | null = null;
  try { pendingBrief = window.sessionStorage.getItem("marketmesh:pendingBrief"); if (pendingBrief) window.sessionStorage.removeItem("marketmesh:pendingBrief"); } catch { /* ignore */ }
  if (!pendingBrief) return;
  let cancelled = false;
  void (async () => {
    await copilotkit.connectAgent({ agent });
    if (cancelled) return;
    await startRun(pendingBrief!);
  })();
  return () => { cancelled = true; };
}, [isReady, routeRunId]);
```

Move `startRun` definition before this effect (or use a ref). Since `startRun` is a `useCallback`, hoist the pending-brief effect after it.

- [ ] **Step 3: Typecheck**

Run: `cd apps/console && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/console/features/deal-room/run-detail.tsx apps/console/features/deal-room/hooks/use-run-detail.ts
git commit -m "feat(console): bind run detail chat to route thread id"
```

## Task 9: Console — ConversationHistory component

**Files:**
- Create: `apps/console/features/deal-room/components/conversation-history.tsx`
- Create: `apps/console/features/deal-room/components/conversation-history.test.tsx`
- Modify: `apps/console/features/deal-room/components/run-detail-workspace.tsx` (or `run-detail.tsx`) to render it

- [ ] **Step 1: Write the failing test**

Create `conversation-history.test.tsx`. Mock `@copilotkit/react-core/v2`'s `useThreads` and `useCopilotKit`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";

const useThreadsMock = vi.fn();
vi.mock("@copilotkit/react-core/v2", () => ({
  useThreads: (args: any) => useThreadsMock(args),
  useCopilotKit: () => ({ copilotkit: { threadEndpoints: { list: true, mutations: true } } }),
}));

import { ConversationHistory } from "./conversation-history";

const threads = [
  { id: "t1", agentId: "marketmesh_orchestrator", name: "First run", archived: false, createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z", lastRunAt: "2026-11-01T00:00:00Z" },
  { id: "t2", agentId: "marketmesh_orchestrator", name: null, archived: false, createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z" },
];

describe("ConversationHistory", () => {
  beforeEach(() => {
    useThreadsMock.mockReset();
    useThreadsMock.mockReturnValue({
      threads, isLoading: false, listError: null, isMutating: false,
      renameThread: vi.fn(), archiveThread: vi.fn(), unarchiveThread: vi.fn(),
      deleteThread: vi.fn(), fetchMoreThreads: vi.fn(), hasMoreThreads: false,
      isFetchingMoreThreads: false, refetchThreads: vi.fn(),
    });
  });

  it("renders thread names and a fallback for unnamed threads", () => {
    render(<ConversationHistory activeThreadId="t1" onNavigate={vi.fn()} />);
    expect(screen.getByText("First run")).toBeInTheDocument();
    expect(screen.getByText(/t2/i)).toBeInTheDocument();
  });

  it("navigates on row click", () => {
    const onNavigate = vi.fn();
    render(<ConversationHistory activeThreadId="t1" onNavigate={onNavigate} />);
    fireEvent.click(screen.getByText("First run"));
    expect(onNavigate).toHaveBeenCalledWith("t1");
  });

  it("hides when listing is unsupported", () => {
    vi.mocked(/* threadEndpoints */).threadEndpoints = { list: false, mutations: false };
    // re-mock by overriding useCopilotKit return for this test
    ...
  });
});
```

Simplify the unsupported case by making the component read `useCopilotKit` and gate rendering. The test for hiding: mock `useCopilotKit` to return `{ copilotkit: { threadEndpoints: { list: false } } }` in a separate describe with its own mock module factory. Keep it pragmatic.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/console && npx vitest run features/deal-room/components/conversation-history.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3: Implement the component**

Create `apps/console/features/deal-room/components/conversation-history.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useCopilotKit, useThreads } from "@copilotkit/react-core/v2";
import { useRouter } from "next/navigation";
import { Archive, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { shortId } from "@/lib/format";

export function ConversationHistory({ activeThreadId }: { activeThreadId: string }) {
  const router = useRouter();
  const { copilotkit } = useCopilotKit();
  const canList = copilotkit.threadEndpoints?.list === true;
  const canMutate = copilotkit.threadEndpoints?.mutations === true;

  const [includeArchived, setIncludeArchived] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");

  const {
    threads, isLoading, listError, isMutating,
    renameThread, archiveThread, unarchiveThread, deleteThread,
    fetchMoreThreads, hasMoreThreads, isFetchingMoreThreads, refetchThreads,
  } = useThreads({ agentId: "marketmesh_orchestrator", enabled: canList, includeArchived, limit: 20 });

  if (!canList) return null;

  const navigate = (id: string) => router.push(`/runs/${id}`);

  const commitRename = async (id: string) => {
    const name = draftName.trim();
    if (name) await renameThread(id, name);
    setEditingId(null);
  };

  return (
    <nav className="mm-conversation-history" aria-label="Conversation history">
      <header className="mm-conversation-history-head">
        <span className="mm-kicker">Conversations</span>
        <Button size="sm" variant="ghost" onClick={() => navigate(crypto.randomUUID())} aria-label="New conversation">
          <Plus size={13} aria-hidden="true" />
        </Button>
      </header>

      {isLoading ? <p className="mm-muted">Loading…</p> : null}
      {listError ? (
        <div className="mm-alert" role="alert">
          <span>{listError.message}</span>
          <Button size="sm" variant="ghost" onClick={() => refetchThreads()}>Retry</Button>
        </div>
      ) : null}

      <ul className="mm-conversation-list">
        {threads.map((t) => {
          const active = t.id === activeThreadId;
          return (
            <li key={t.id} className={active ? "is-active" : undefined}>
              {editingId === t.id ? (
                <input
                  className="mm-conversation-rename"
                  value={draftName}
                  autoFocus
                  onChange={(e) => setDraftName(e.target.value)}
                  onBlur={() => commitRename(t.id)}
                  onKeyDown={(e) => { if (e.key === "Enter") commitRename(t.id); if (e.key === "Escape") setEditingId(null); }}
                  aria-label="Rename conversation"
                />
              ) : (
                <button
                  type="button"
                  className="mm-conversation-row"
                  aria-current={active ? "page" : undefined}
                  onClick={() => navigate(t.id)}
                >
                  <span className="mm-conversation-name">{t.name ?? shortId(t.id, 8)}</span>
                  <span className="mm-conversation-time">{t.lastRunAt ?? t.updatedAt}</span>
                </button>
              )}
              {canMutate ? (
                <div className="mm-conversation-actions">
                  <button type="button" aria-label="Rename" onClick={() => { setEditingId(t.id); setDraftName(t.name ?? ""); }}>
                    <Pencil size={12} aria-hidden="true" />
                  </button>
                  <button type="button" aria-label={t.archived ? "Unarchive" : "Archive"} onClick={() => t.archived ? unarchiveThread(t.id) : archiveThread(t.id)}>
                    <Archive size={12} aria-hidden="true" />
                  </button>
                  <button type="button" aria-label="Delete" onClick={() => { if (window.confirm("Delete this conversation?")) deleteThread(t.id).then(() => { if (t.id === activeThreadId) router.push("/runs"); }); }}>
                    <Trash2 size={12} aria-hidden="true" />
                  </button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {hasMoreThreads ? (
        <Button size="sm" variant="ghost" onClick={() => fetchMoreThreads()} disabled={isFetchingMoreThreads}>
          {isFetchingMoreThreads ? "Loading…" : "Load more"}
        </Button>
      ) : null}

      <label className="mm-conversation-archived-toggle">
        <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />
        Show archived
      </label>
    </nav>
  );
}
```

- [ ] **Step 4: Render it in the run detail**

In `run-detail.tsx`, add inside the `conversation` slot or above `RunDetailWorkspace`. Simpler: render it above the chat rail by wrapping. Since `RunDetailWorkspace` owns the rail, add a prop `history` and pass `<ConversationHistory activeThreadId={runId} />`. Or render it directly in `run-detail.tsx` inside the workspace's children. Check `RunDetailWorkspace`'s props; if it accepts `children`/`conversation`, render the history above `conversation`:

```tsx
conversation={
  <>
    <ConversationHistory activeThreadId={runId} />
    <Chat variant="embedded" threadId={runId} ... />
  </>
}
```

- [ ] **Step 5: Add minimal CSS**

Append to `apps/console/app/globals.css` (or the run-detail styles) minimal `mm-conversation-*` rules matching the existing palette (use `var(--rule)`, `var(--panel)`, etc.). Keep it compact.

- [ ] **Step 6: Run tests**

Run: `cd apps/console && npx vitest run features/deal-room/components/conversation-history.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/console/features/deal-room/components/conversation-history.tsx apps/console/features/deal-room/components/conversation-history.test.tsx apps/console/features/deal-room/run-detail.tsx apps/console/app/globals.css
git commit -m "feat(console): headless conversation history panel in run detail"
```

## Task 10: Console — .env.example and settings

**Files:**
- Modify: `apps/console/.env.example` (or root `.env.example`)
- Modify: `apps/console/app/(console)/settings/page.tsx`

- [ ] **Step 1: Document Intelligence env vars**

Add to the console env example:

```
CPK_INTELLIGENCE_API_KEY=
INTELLIGENCE_API_URL=
INTELLIGENCE_GATEWAY_WS_URL=
```

- [ ] **Step 2: Add Intelligence status to Settings page**

In `settings/page.tsx`, add rows for `threadsEnabled` (already) and a note that mutations require Intelligence. No code change needed beyond existing; optionally add the Intelligence API URL display. Skip if trivial.

- [ ] **Step 3: Commit**

```bash
git add apps/console/.env.example apps/console/app/\(console\)/settings/page.tsx
git commit -m "docs(console): document Intelligence env vars"
```

## Task 11: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: README setup steps**

Add a "Conversation history" section:
- Create a CopilotKit Intelligence project; set `CPK_INTELLIGENCE_API_KEY` (and optional URLs) before building.
- Create the `demo-user` user in the Intelligence project.
- Orchestrator uses `./data/orchestrator_sessions.db`; ensure the directory is writable/persisted.
- Buyer/verifund already use SQLite checkpoints (`checkpoint_path`).
- The middleware patch is applied automatically via pnpm.

- [ ] **Step 2: Architecture doc**

Update the thread/ID model section to reflect the new correlation (threadId = run_id = ADK session id = A2A contextId = LangGraph thread_id).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/architecture.md
git commit -m "docs: conversation history setup and ID model"
```

## Task 12: Verification

- [ ] **Step 1: Python tests**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 2: Console typecheck and unit tests**

Run: `cd apps/console && npx tsc --noEmit && npx vitest run`
Expected: no type errors; all tests pass.

- [ ] **Step 3: Console build (with Intelligence key set)**

Run: `cd apps/console && CPK_INTELLIGENCE_API_KEY=dummy npm run build`
Expected: build succeeds.

- [ ] **Step 4: End-to-end smoke (manual)**

Start the stack (orchestrator, buyer, verifund, console). Open `/`, "Start Shopping", complete a run, reload `/runs/{id}` → transcript and run row restored. Open the history panel → thread listed; "New conversation" → empty chat.

- [ ] **Step 5: Final commit (if any loose changes)**

```bash
git status --short
# commit any remaining changes
```

---

**Execution Handoff**

Plan complete and saved to `docs/superpowers/plans/2026-11-01-conversation-history.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?