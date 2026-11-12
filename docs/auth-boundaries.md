# Authentication boundaries: Clerk users and service credentials

**Audience:** engineers adding console routes, proxies, agent tools, or service-to-service calls.  
**Type:** explanation, with reference tables for day-to-day decisions.

This document explains why MarketMesh has two authentication systems that look
redundant but answer different questions. It describes the current code, not the
target end state; the buyer and seller Clerk migrations are in progress and are
linked at the end.

## The short version

- **Clerk answers “who is this person, and which organization are they acting in?”**
  It guards browser-facing pages and console route handlers.
- **Service credentials answer “which workload is calling, and is it allowed to?”**
  They authenticate calls between processes that have no browser and no Clerk
  session.
- **They compose.** The console verifies the Clerk session, derives the tenant,
  and only then attaches a service credential server-side. The browser never sees
  that credential, and internal services never see the Clerk session.

If a request has a human behind it, Clerk gates it. If a request is machine-to-machine,
a service credential gates it. A route that serves user-scoped data needs both
facts: the Clerk session decides *whose* data may be requested; the service
credential proves *which service* is asking.

## Two different questions

| Question | Answered by | Example |
| --- | --- | --- |
| Who is signed in? | Clerk session | A buyer opens the console chat |
| Which organization is active? | Clerk active organization | A seller admin configures an agent for one org |
| Which process is calling? | Service credential | The orchestrator fetches the marketplace catalog |
| May this process read this tenant’s run? | Service credential **plus** tenant proof | Console reads a run for the signed-in user’s org |

This is the distinction the repository already documents for seller onboarding:
Clerk authenticates administrators, while buyer/seller agents authenticate as
machines (`docs/superpowers/specs/seller-agent-config-seller-onboarding.md`, §14).
The buyer Clerk migration keeps the same split: “Clerk for console/user actions,
internal service auth for trusted automation”
(`docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md`,
decisions 1 and 6).

## The request path

```text
Browser
  │  Clerk session cookie
  ▼
Next.js console
  │  middleware.ts → clerkMiddleware()
  │  route/layout → auth.protect() / consoleSession()
  │
  ├─ console/internal service credentials ──► Buyer agent
  │                                             (runs, trace, settlement,
  │                                              marketplace catalog)
  │
  └─ CopilotKit runtime (auth.protect) ──► ADK orchestrator (:9000)
                                               │
                                               │ x-verifund-internal-token
                                               ▼
                                           Buyer agent (:9100)
                                               │
                                               │ A2A bearer tokens
                                               ▼
                                       Registry + seller agents
```

Two hops matter for this document:

1. **Browser → console.** Clerk owns this. The user must have a session before any
   user-scoped data is read or written.
2. **Console/orchestrator → buyer → sellers.** No browser. Clerk sessions do not
   exist here. The caller presents a service credential, and the callee enforces
   whatever tenant proof that credential requires.

## What Clerk owns

- `apps/console/middleware.ts` installs `clerkMiddleware()`. This makes auth state
  available but **does not protect routes by itself**.
- Protection is explicit and per surface:
  - `apps/console/app/(console)/layout.tsx` calls `consoleSession()`, which calls
    `auth.protect()` and returns `{ userId, orgId, orgRole }`.
  - Route handlers call `auth.protect()` directly, and user-scoped proxies also
    call `consoleSession()` to obtain the org.
  - `apps/console/app/api/copilotkit/[[...slug]]/route.ts` protects every method
    before starting an agent run.
- Clerk Organizations provide the tenant context for org-scoped console
  surfaces. The org id used in downstream calls must always come from the
  session, never from a request body or query parameter supplied by the client.

Clerk is **not** a machine identity provider for the agent processes in this repo.
The Python orchestrator has no Clerk SDK or session; the buyer agent does not
verify Clerk session tokens (it forwards a configured buyer id to the control
plane). Making them verify sessions would mean distributing user tokens to
non-browser services, which is the opposite of the intended exposure model.

## What service credentials own

The buyer agent is the main internal boundary. It accepts two static credentials,
both compared with `secrets.compare_digest` and both failing closed when unset or
wrong (`apps/buyer_agent/buyer_agent/console_api.py`):

| Header | Meaning | Configuration |
| --- | --- | --- |
| `x-marketmesh-console-token` | The console server is calling; the console is expected to have verified the user first | `BUYER_CONSOLE_API_TOKEN` / `settings.console_api_token` |
| `x-verifund-internal-token` | A trusted service (console server, orchestrator, Verifund, seller services) is calling | `BUYER_INTERNAL_TOKEN` / `settings.internal_api_token` |

Tenant proof travels alongside the credential:

- `x-buyer-organization-id`, or an `organization_id` query parameter, identifies
  the tenant the console derived from the Clerk session
  (`apps/console/lib/buyer-proxy.ts`).
- For the internal-token path, `_authorize_run_access` **requires**
  `organization_id` (400 when missing) and returns 404 when it does not match the
  run’s stored org.
- For the console-token path, the org check is applied only when the caller
  supplies one; the buyer trusts the console to have verified the user first.
  That trust is the reason the next section exists.

A2A seller calls are a third category: per-seller bearer tokens held server-side
by the services that make A2A calls. They are never placed in browser code. See
`docs/a2a-extension.md` for the A2A transport contract.

## The trust boundary

The console server is a **confused-deputy boundary**: it holds a credential that
can read data across tenants, so it must be impossible for a client to make it
use that credential for the wrong tenant.

The safe pattern is:

1. `auth.protect()` runs before any work.
2. The org comes from `consoleSession()`, not from the request.
3. The console attaches the service credential and the derived org server-side.
4. The callee verifies the credential, and verifies the org against the resource
   it is about to return.

The current buyer implementation enforces step 4 strictly only on the
internal-token path. On the console-token path it delegates tenant checking to
the console. That delegation is acceptable only if **every** route that attaches
the console token has already verified the Clerk session. Two catalog proxies do
not (see gaps below), and catalog data is public, so the immediate impact is
limited — but the invariant is “Clerk first” for any route that can reach
user-scoped data.

## Choosing the right mechanism

| Situation | Mechanism | Notes |
| --- | --- | --- |
| New console page under `(console)` | `consoleSession()` in layout or page | Derive org from the session |
| New console API route returning user data | `auth.protect()` + `consoleSession()`, then internal token + org to the buyer | Never trust client-supplied org |
| Console proxy for public catalog data | May skip Clerk only if the data is genuinely public; say so in the route | Current exceptions are listed below |
| Orchestrator or other Python service → buyer | `x-verifund-internal-token` | Uses `BUYER_INTERNAL_URL` / `BUYER_INTERNAL_TOKEN` |
| Service → service where the callee has no tenant | Internal token only | Catalog reads are the example |
| Browser → any service | Never direct; go through a console route | No tokens in client bundles |
| Clerk webhook | Public route, signature verified downstream | `svix-*` headers are forwarded to the control plane |

## Rules for new code

- **Clerk first.** Any handler that can reach user-scoped data calls
  `auth.protect()` (or `consoleSession()`) before reading the request.
- **Org from session only (in console handlers).** Do not accept an org id from a
  client body, query, or header as proof of authorization. It may be used only
  after the session-derived org has been checked.
- **Tokens stay server-side.** Never return them in responses, render them in the
  client, or accept them as user input. Console proxies attach them in the route
  handler.
- **Fail closed.** Missing or malformed credentials are 401; missing tenant proof
  on the internal path is 400; mismatched tenant is 404, so existence does not
  leak.
- **Constant-time comparison.** Use `secrets.compare_digest` (Python) or the
  equivalent; never `==` on secrets.
- **No secret logging.** Do not log headers, tokens, or internal URLs in tool
  results returned to the model.
- **Document exceptions.** A route that deliberately skips Clerk must say why in
  a comment and must not return user-scoped data.

## Known gaps and risks

These are current-state observations, not endorsements.

1. **Two catalog proxies skip Clerk.** `apps/console/app/api/marketplace/products/route.ts`
   and `apps/console/app/api/registry/sellers/route.ts` do not call
   `auth.protect()`. Both serve public catalog data (sellers expose `/api/catalog`
   publicly), so the exposure is catalog contents rather than tenant data. The
   marketplace proxy still attaches the console token, which means it acts as an
   unauthenticated relay to the buyer.
   `apps/console/app/api/webhooks/clerk/route.ts` is also unguarded by design and
   forwards verification headers to the control plane.
2. **Shared credentials are broad.** Neither token has per-caller identity,
   expiry, scopes, or an automated rotation story. The internal token also
   authorizes run, trace, and settlement internals, not just catalog reads.
3. **The console-token path trusts the console.** It does not require an
   organization id, so a mistaken proxy route can read another tenant’s run. The
   internal-token path is stricter.
4. **Header proliferation.** The buyer agent also uses other legacy headers
   (`x-marketmesh-internal-token`, `x-verifund-agent-token`) that the buyer Clerk
   migration consolidates. Do not add new callers to those without checking that
   spec.
5. **Architecture doc drift.** `docs/architecture.md` says the console never
   receives seller bearer tokens, but the CopilotKit A2A middleware injects
   `BUYER_AGENT_TOKEN` / `SELLER_NORTHWIND_TOKEN` for seller calls
   (`apps/console/app/api/copilotkit/[[...slug]]/route.ts`). Treat the route as
   the source of truth until the architecture text is reconciled.

## Direction of travel

The target model, already scoped in the buyer and seller Clerk migration specs,
is:

- **Clerk** for every human identity, session, and organization decision.
- **Explicit, least-privilege service auth** for agent and automation boundaries.
- **No legacy buyer bearer or approval tokens** on migrated user paths.

Two mechanisms can replace the shared internal token without reintroducing user
sessions into services:

- Clerk machine-to-machine OAuth tokens, scoped to an organization and a small
  permission set; or
- a short-lived signed service JWT from the console, with an audience, a scope
  such as `catalog:read` or `runs:read`, and a tenant claim that the buyer
  verifies.

Either is a separate auth migration. Until then, treat the shared token as a
broad credential and keep the console boundary strict.

## Where the code lives

| Concern | File |
| --- | --- |
| Clerk middleware | `apps/console/middleware.ts` |
| Session + org derivation | `apps/console/lib/console-session.ts` |
| Console layout guard | `apps/console/app/(console)/layout.tsx` |
| CopilotKit route guard | `apps/console/app/api/copilotkit/[[...slug]]/route.ts` |
| Console → buyer proxy and org propagation | `apps/console/lib/buyer-proxy.ts` |
| Buyer token checks and run authorization | `apps/buyer_agent/buyer_agent/console_api.py` |
| Orchestrator buyer credentials | `apps/orchestrator_agent/orchestrator_agent/settings.py`, `agent.py` |
| Public catalog proxies | `apps/console/app/api/marketplace/products/route.ts`, `apps/console/app/api/registry/sellers/route.ts` |
| Clerk webhook proxy | `apps/console/app/api/webhooks/clerk/route.ts` |

## Related documents

- `docs/architecture.md` — service boundaries and protocol split.
- `docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md` — buyer Clerk migration and the internal-auth model for automation.
- `docs/superpowers/specs/2026-11-07-seller-workspace-clerk-access-design.md` — seller parity migration.
- `docs/superpowers/specs/seller-agent-config-seller-onboarding.md` §14 — Clerk identity versus A2A machine identity.
- `docs/a2a-extension.md` — A2A transport and agent-card authentication.
