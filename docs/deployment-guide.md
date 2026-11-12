# Deployment Guide: Render Backend + Vercel Console

**Document type:** How-to guide
**Audience:** The team deploying the MarketMesh / Verifund demo
**Goal:** A working hosted demo with the backend on Render and the console on Vercel.

This guide reflects the deployment architecture selected for the current demo window:

| Decision | Choice |
| --- | --- |
| Backend scope | Full six-service topology |
| Settlement mode | `VERIFUND_MODE=sandbox` (real PayPal Sandbox) |
| Console platform | Vercel |
| Console → backend | Public Render URLs (no private networking) |
| Database | Render Postgres (free tier) |
| LLM mode | `live` (Nebius) |
| Auth | Clerk (test keys) |
| Initial data | Sellers onboarded through the console UI |

> **Note:** the PostgreSQL migration in [Step 1](#step-1--migrate-to-postgres) is implemented on this branch, so PostgreSQL is a supported backend. The free-tier limitations are still real. Read [Before you start](#before-you-start--remaining-blockers) before committing. A zero-code-change alternative is listed in [Alternative topology](#alternative-topology-paid-render--sqlite).

---

## Prerequisites

- A Render account with the repo connected.
- A Vercel account.
- A PayPal Developer account with sandbox accounts (platform, buyer, and one per seller).
- A Clerk account (test instance is acceptable for this demo).
- A Nebius API key.
- The repo checked out locally for the PostgreSQL migration and Docker fixes.

---

## Architecture

| Layer | Service | Render name | Port | Public URL |
| --- | --- | --- | --- | --- |
| Backend | orchestrator | `orchestrator` | 9000 | `https://orchestrator.onrender.com` |
| Backend | buyer | `buyer` | 9100 | `https://buyer.onrender.com` |
| Backend | registry | `registry` | 9105 | `https://registry.onrender.com` |
| Backend | seller-shared | `seller-shared` | 9200 | `https://seller-shared.onrender.com` |
| Backend | verifund control plane | `control-plane` | 9300 | `https://control-plane.onrender.com` |
| Backend | verifund agent | `verifund-agent` | 9301 | `https://verifund-agent.onrender.com` |
| Database | Render Postgres | `marketmesh` | 5432 | internal |
| Frontend | console | Vercel project | — | `https://<project>.vercel.app` |

All six backend services are **public web services**. Free-tier services cannot receive private network traffic, and the Vercel console must reach them over public HTTPS. They communicate with each other via their `*.onrender.com` URLs.

### Merged gateway topology

`render.yaml` deploys **one** Docker service, `gateway`, on
`https://gateway-795m.onrender.com`. It imports each service's existing FastAPI app
and mounts it under a path prefix, so the logical services above share one
origin and one port:

| Prefix | Service | Internal port (standalone) |
| --- | --- | --- |
| `/orchestrator` | orchestrator | 9000 |
| `/buyer` | buyer | 9100 |
| `/registry` | registry | 9105 |
| `/sellers` | seller-shared | 9200 |
| `/control-plane` | verifund control plane | 9300 |
| `/verifund-agent` | verifund agent | 9301 |

`GET https://gateway-795m.onrender.com/health` is the Render health check. The
prefix is stripped before dispatch, so every service keeps its existing
unprefixed routes: a seller card lives at
`https://gateway-795m.onrender.com/sellers/northwind-audio/.well-known/agent-card.json`.

Run the same topology locally with `make dev` (alias `make dev-gateway`). It
starts `python -m gateway` on `http://127.0.0.1:10000` plus the console, with
every inter-service URL rewritten to a prefix. `make down` stops it. Use
`make dev GATEWAY=0` (alias `make dev-legacy`) for the six separate processes
when you need per-service ports and logs.

#### Merged-gateway env var ownership

All six services read env vars in one process, so these collisions matter:

| Var | Readers | Resolution |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | buyer (fallback), seller | Set `PUBLIC_BASE_URL=https://gateway-795m.onrender.com/sellers` for the seller and `BUYER_PUBLIC_BASE_URL=https://gateway-795m.onrender.com/buyer` for the buyer |
| `DATABASE_URL` | buyer, registry, seller, verifund-agent (fallback) | Never set it; always set the service-specific `*_DATABASE_URL` |
| `CHECKPOINT_PATH` | buyer, verifund-agent (fallback) | Never set it; always set `BUYER_CHECKPOINT_PATH` / `VERIFUND_AGENT_CHECKPOINT_PATH` |
| `PORT` | every service's settings (unused for binding) | Set once; the gateway binds it |
| `HOST` | verifund-agent settings, gateway | Set `0.0.0.0` |
| `VERIFUND_URL` | buyer, seller | `https://gateway-795m.onrender.com/control-plane` |
| `BUYER_INTERNAL_URL` | orchestrator, verifund-agent | `https://gateway-795m.onrender.com/buyer` |
| `SELLER_SHARED_URL` | control plane, console | `https://gateway-795m.onrender.com/sellers` |
| `VERIFUND_AGENT_URL` | orchestrator, verifund-agent | `https://gateway-795m.onrender.com/verifund-agent` |

```mermaid
flowchart LR
  Judge[Judge] -->|HTTPS| Console[Console on Vercel]
  Console -->|server-side API routes| Orchestrator[Orchestrator]
  Console -->|server-side API routes| Buyer[Buyer]
  Console -->|server-side API routes| Registry[Registry]
  Console -->|server-side API routes| Sellers[Seller-shared]
  Console -->|server-side API routes| Control[Control plane]
  Orchestrator --> Buyer
  Orchestrator --> Sellers
  Buyer --> Registry
  Buyer --> Control
  Control --> PayPal[PayPal Sandbox]
  PayPal -->|webhook| Control
  Agent[Verifund agent] --> Buyer
  Orchestrator --> Agent
```

---

## Before you start — remaining blockers

### 1. PostgreSQL is supported; know what it does and does not cover

The drivers, the dialect-aware helpers, the checkpoint savers and the ADK session store are in place, so a `postgresql+psycopg://` URL now works for every service. What it does **not** change:

- **Schema management is still runtime DDL.** Tables are created with `metadata.create_all` plus idempotent `ALTER TABLE` column checks, not migrations. Fine for a demo; not a production schema history.
- **Evidence files stay on local disk.** `VERIFUND_EVIDENCE_DIR` still holds uploaded evidence, which the database does not persist. On free tier that directory is ephemeral.
- **Tenancy stays application-enforced.** No row-level security is added by the Postgres path.
- **One instance, several databases.** Render's free tier permits a single Postgres instance, so each service gets its own database inside it (see [Step 1](#step-1--migrate-to-postgres)).
- **Defaults still point at SQLite.** Local development and the unit suite keep using SQLite; only a deployed URL switches a service to PostgreSQL.

### 2. Free-tier limitations

- **Cold starts:** free services spin down after 15 minutes without traffic and take about one minute to spin up. This breaks long-lived SSE streams.
- **750 free instance hours per month:** six always-on services consume roughly 4,380 hours per month, exhausting the quota in about five days.
- **No persistent disks:** local SQLite files and uploaded evidence are lost on every redeploy, restart, and spin-down.
- **No shell or one-off jobs:** seeding cannot be a manual Render Shell run.
- **No private networking:** free services cannot receive private traffic, so every service must be public.
- **No health checks on free tier:** Render restarts crashed services, but there is no health-check-driven restart or zero-downtime deploy.

### 3. Evidence and checkpoints are ephemeral

The control plane writes evidence files to `VERIFUND_EVIDENCE_DIR`, and the buyer/seller/verifund-agent keep LangGraph checkpoints on local disk. With no persistent disk:

- Postgres can hold the graph checkpoints (via `langgraph-checkpoint-postgres`), but **not** the evidence files.
- Evidence files need object storage (S3, Cloudflare R2) or a paid persistent disk.

---

## Step 1 — Migrate to Postgres

**Status: implemented.** The drivers, dialect-aware database helpers, checkpoint savers and ADK session store ship on this branch. Choose a PostgreSQL target with URLs and every service switches backend; leave the defaults alone and local development keeps using SQLite.

What the implementation consists of, for review:

- `psycopg[binary,pool]` and `langgraph-checkpoint-postgres` are dependencies.
- `commerce_core.db` owns the dialect split: `configure_database` (SQLite PRAGMAs vs. a UTC session), `existing_columns` (`information_schema.columns` vs. `PRAGMA table_info`), `dialect_insert` (PostgreSQL vs. SQLite upsert), `portable_ddl`, and `row_was_written`.
- `commerce_core.checkpoints.open_checkpointer` picks `AsyncPostgresSaver` for a `postgresql+psycopg://` URL and `AsyncSqliteSaver` for a file path.
- Insert-result checks use `RETURNING`. `psycopg` reports `rowcount == -1` for INSERTs, so duplicate detection and optimistic guards would otherwise invert.
- The seller review stores (`shared_review_store`, `agreement_store`) run on either backend instead of raw `sqlite3`.

### 1.1 Provision the databases

Render's free tier allows one Postgres instance, so each service gets a database inside it: `buyer`, `registry`, `sellers`, `verifund`, `verifund_agent`, `orchestrator`. Render exposes one connection string per instance; the script creates the rest and prints the URLs to paste into the Blueprint.

```bash
uv run python scripts/provision_postgres.py \
  --base-url "postgresql://USER:PASSWORD@HOST/DATABASE" \
  --show-passwords
```

Then set, on the `gateway` service:

| Variable | Value |
| --- | --- |
| `BUYER_DATABASE_URL` | `postgresql+psycopg://…/buyer` |
| `REGISTRY_DATABASE_URL` | `postgresql+psycopg://…/registry` |
| `SELLER_SHARED_DB_URL` | `postgresql+psycopg://…/sellers` |
| `VERIFUND_DATABASE_URL` | `postgresql+psycopg://…/verifund` |
| `VERIFUND_AGENT_DATABASE_URL` | `postgresql+psycopg://…/verifund_agent` |
| `ORCHESTRATOR_SESSION_DB_URL` | `postgresql+psycopg://…/orchestrator` |
| `BUYER_CHECKPOINT_URL` | `postgresql+psycopg://…/buyer` |
| `SELLER_CHECKPOINT_URL` | `postgresql+psycopg://…/sellers` |
| `VERIFUND_AGENT_CHECKPOINT_URL` | `postgresql+psycopg://…/verifund_agent` |

Leave `DATABASE_URL` and the bare `CHECKPOINT_PATH` unset. The merged gateway runs every service in one process, and those generic names would collide (see the env-var ownership table above).

### 1.2 Test locally first

`docker-compose.yml` now includes a PostgreSQL 18 service that creates the six databases on first start:

```bash
docker compose up -d postgres
uv run python scripts/provision_postgres.py \
  --base-url "postgresql://marketmesh:marketmesh@127.0.0.1:5432/marketmesh"
```

The Compose init script already created them, so the command should report that all databases are present. Point the service URLs in `docker-compose.yml` at PostgreSQL to exercise that path locally.

---

## Step 2 — Deploy the backend on Render

### 2.1 Docker build fixes

- `Dockerfile.python` copies `packages`, `apps/*`, and `scripts`, but **not** `docs/templates`. That is fine when sellers are onboarded through the UI, but `make seed-demo` will fail inside the container.
- `apps/console/Dockerfile` is broken: it runs `npm ci` and copies `package-lock.json`, but the repo only contains `pnpm-lock.yaml`. This does not affect Vercel, but fix it if the console is ever moved to Render.

### 2.2 Render Blueprint

`render.yaml` at the repository root deploys the **merged gateway** as a single
Docker web service. Do not paste a six-service blueprint: this branch mounts all
six FastAPI apps behind one process (see
[Merged gateway topology](#merged-gateway-topology)).

Apply it with **Render → New → Blueprint**, select this repository and the
`deploy/render` branch. Render generates the internal secrets marked
`generateValue: true` and prompts for every `sync: false` value (see
[2.4 Secrets](#24-secrets-generated-vs-supplied)).

| Item | Value |
| --- | --- |
| Service | `gateway` (Docker, `python -m gateway`) |
| Port | `10000` (`PORT`) |
| Health check | `/health` |
| Database | one free Postgres instance, `marketmesh` |
| Env group | `gateway-shared` for secrets shared by all six services |

Three values are easy to get wrong because the merged process reads each one
once for every service:

- `REGISTRY_URL` must be `https://gateway-795m.onrender.com/registry`. Its default is
  `http://127.0.0.1:9100`, so seller activation silently fails to publish an
  Agent Card.
- The registry authenticates writes with `ADMIN_TOKEN`, while the control plane
  sends `REGISTRY_ADMIN_TOKEN`. Set both to the same secret.
- `VERIFUND_AGENT_CARD_URL` must be the gateway-prefixed card URL; its default
  is `http://127.0.0.1:9301/...`.

The complete list of keys and values lives in `render.yaml`; the secrets are the
`generateValue` and `sync: false` entries.

### 2.3 Notes on the Blueprint

- `PORT` is set once, on `gateway`. Render routes public traffic to that port; the default is already `10000`, which is what the Blueprint uses.
- `generateValue: true` makes Render generate a base64-encoded 256-bit value on the first sync and keep it afterwards. `sync: false` means Render prompts for the value instead.
- The `*.onrender.com` subdomains assume the service names are available. Verify the exact URLs in the Render dashboard after the first deploy and correct any env vars that reference them.
- `ALLOWED_CARD_HOSTS` and `ALLOWED_CARD_URLS` control which Agent Card URLs the buyer and registry will fetch. With dynamic onboarding, `ALLOWED_CARD_URLS` can stay empty and the shared host is allowed.
- Free-tier services cannot use `healthCheckPath` for restart-driven recovery; Render still restarts crashed processes.

### 2.4 Secrets: generated vs. supplied

The gateway validates the control-plane settings at startup
(`verifund_control_plane/settings.py`). In sandbox mode the ops, seller-token and
link secrets must each be at least 32 bytes and must not be one of the
`DEFAULT_SECRETS` placeholders, or the process exits before it binds a port.
Keep that check in mind when changing any of the values below.

**Render generates these on the first Blueprint sync** (`generateValue: true`),
so they cannot be forgotten or left at a placeholder:

| Key | Notes |
| --- | --- |
| `VERIFUND_OPS_TOKEN` | Also read by the Vercel console — copy it there |
| `VERIFUND_SELLER_TOKEN_SECRET` | Used to sign seller tokens |
| `VERIFUND_LINK_SECRET` | Used to sign checkout/return links |
| `BUYER_INTERNAL_TOKEN` | Also read by the Vercel console — copy it there |
| `SELLER_INTERNAL_TOKEN` | Internal seller calls |
| `VERIFUND_AGENT_A2A_TOKEN` | Agent A2A calls |
| `VERIFUND_AGENT_INTERNAL_TOKEN` | Buyer → agent calls |

The console runs on Vercel, outside the Blueprint. After each Blueprint sync,
copy the generated `VERIFUND_OPS_TOKEN` and `BUYER_INTERNAL_TOKEN` from the
`gateway-shared` group into the console's Vercel environment; otherwise
console → control-plane and console → buyer calls return 401.

**These stay `sync: false`** because Render cannot generate them correctly:

| Key | Why it is manual |
| --- | --- |
| `ADMIN_TOKEN`, `REGISTRY_ADMIN_TOKEN` | The registry and the control plane must use the **same** value; generating them separately would produce two different secrets |
| `VERIFUND_RECEIPT_KEYS`, `VERIFUND_RECEIPT_ACTIVE_KID` | The key is JSON (`{"<kid>":"<secret>"}`) and its inner key must equal the active kid, so both must be entered together. The kid must not be `dev-1`, and the secret must be at least 32 bytes |
| `VERIFUND_SELLER_PAYOUT_EMAILS` | JSON map of seller ID → payout email; must be non-empty, unique, and exclude the platform/buyer addresses |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | PayPal sandbox credentials; the webhook must be registered for the gateway host |
| `PAYPAL_PLATFORM_EMAIL`, `PAYPAL_BUYER_EMAIL` | Sandbox account addresses |
| `NEBIUS_API_KEY` | Live LLM calls (`MARKETMESH_LLM_MODE=live`) |
| `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, `CLERK_WEBHOOK_SIGNING_SECRET` | Clerk dashboard values |

`generateValue` never overwrites an existing value. If a key already holds a
placeholder, change it to a real value in the dashboard or delete the key from
the group and sync the Blueprint again to have Render generate a fresh one.
`sync: false` values are prompted once and preserved across syncs.

---

## Step 3 — Deploy the console on Vercel

1. Import the repository into Vercel and set the **Root Directory** to `apps/console`. Vercel detects `pnpm-lock.yaml` and runs `pnpm install`.
2. Build command: `pnpm run build`. The Next.js `output: "standalone"` setting is harmless on Vercel.
3. Set the environment variables.

   **Server-side:**

   | Variable | Value |
   | --- | --- |
   | `BUYER_AGUI_URL` | `https://gateway-795m.onrender.com/buyer/agui` |
   | `BUYER_API_URL` | `https://gateway-795m.onrender.com/buyer` |
   | `BUYER_A2A_URL` | `https://gateway-795m.onrender.com/buyer` |
   | `BUYER_CONSOLE_API_TOKEN` | shared secret |
   | `BUYER_INTERNAL_TOKEN` | shared secret |
   | `ORCHESTRATOR_AGUI_URL` | `https://gateway-795m.onrender.com/orchestrator` |
   | `ORCHESTRATOR_URL` | `https://gateway-795m.onrender.com/orchestrator` |
   | `REGISTRY_URL` | `https://gateway-795m.onrender.com/registry` |
   | `SELLER_SHARED_URL` | `https://gateway-795m.onrender.com/sellers` |
   | `VERIFUND_CONTROL_PLANE_URL` | `https://gateway-795m.onrender.com/control-plane` |
   | `VERIFUND_OPS_TOKEN` | shared secret |
   | `PAYPAL_CLIENT_SECRET` | PayPal sandbox secret |
   | `CPK_INTELLIGENCE_API_KEY` | optional |

   **Client-side (`NEXT_PUBLIC_*`):**

   | Variable | Value |
   | --- | --- |
   | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key |
   | `NEXT_PUBLIC_MARKETMESH_LLM_MODE` | `live` |
   | `NEXT_PUBLIC_VERIFUND_MODE` | `sandbox` |
   | `NEXT_PUBLIC_PAYPAL_CLIENT_ID` | must equal `PAYPAL_CLIENT_ID` |
   | `NEXT_PUBLIC_PAYPAL_ENVIRONMENT` | `sandbox` |
   | `NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED` | `true` only if a CopilotKit Intelligence key is set |

4. Clerk: add the Vercel domain to Clerk's allowed origins. The bare `clerkMiddleware()` requires the keys at runtime.
5. Function duration: `/api/runs/[runId]/stream` and `/api/copilotkit` stream SSE. Vercel's fluid compute defaults to 300 seconds (Pro: 800 seconds, beta: 1800 seconds), which is sufficient. Set `maxDuration` on those routes if a run takes longer.
6. **Caveat:** `apps/console/app/api/copilotkit/[[...slug]]/route.ts` hardcodes the four demo seller URLs (`northwind-audio`, `circuitforge`, `aurora-supply`, `summit-tech`). If sellers are onboarded with different IDs, update that list or confirm the orchestrator's `mediate_seller_call` path does not depend on it.

---

## Step 4 — Configure PayPal Sandbox

1. Create a PayPal Developer account and a sandbox app. Record `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`.
2. Create a sandbox webhook pointing at `https://gateway-795m.onrender.com/control-plane/webhooks/paypal`. Copy the webhook ID into `PAYPAL_WEBHOOK_ID`.
3. Set `VERIFUND_PUBLIC_BASE_URL=https://gateway-795m.onrender.com/control-plane`. Sandbox mode requires HTTPS; Render provides it.
4. Payer return and cancel URLs are built from `public_base_url` (`/return/{token}` and `/cancel/{token}`) and redirect to the console's `/runs/{runId}`.
5. Create separate sandbox accounts for the platform, the buyer, and each seller. Put the seller emails in `VERIFUND_SELLER_PAYOUT_EMAILS`; the values must be unique.
6. The control plane's sandbox guard refuses default secrets, a missing webhook ID, a non-HTTPS public URL, and the live PayPal host. All of the above must be real values.

See `docs/verifund-paypal-sandbox.md` for the full account, webhook, tunnel, and payout setup.

---

## Step 5 — Configure Clerk

1. Create a Clerk app. This guide uses test keys; see the caveat below.
2. Console: set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY`.
3. Control plane: set `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, and `CLERK_WEBHOOK_SIGNING_SECRET`.
4. Point the Clerk webhook at `https://gateway-795m.onrender.com/control-plane/v1/webhooks/clerk` so tenancy users and organizations sync.
5. Configure the Vercel domain in Clerk.

> **Caveat:** Clerk test keys are intended for development and are rate-limited. For a public demo, production keys are safer. The control plane's real tenancy path expects them.

---

## Step 6 — Onboard the four sellers through the UI

The control plane bootstraps the **buyer agent** automatically on startup (`seed_demo_agents`). Sellers are created dynamically through the console:

1. Sign in to the console with Clerk and create a seller organization at `/seller/onboarding`.
2. Complete the wizard in order:
   1. Profile
   2. Create agent
   3. Config
   4. Policies
   5. Import catalog — paste the YAML from `docs/templates/northwind.yaml`, `circuitforge.yaml`, `aurora.yaml`, or `summit-tech.yaml`
   6. Test
   7. Verification (payout email)
   8. Activate
3. On activation, the control plane publishes the Agent Card to the registry. The buyer polls the registry every 30 seconds and discovers the seller.
4. Repeat for all four sellers. This reproduces the demo's deterministic ranking.

---

## Step 7 — Verify

1. Health:
   - `GET https://<service>.onrender.com/health` for orchestrator, buyer, registry, seller-shared, and control-plane.
   - `GET https://verifund-agent.onrender.com/ready` for the Verifund agent.
2. Registry: `GET https://registry.onrender.com/v1/sellers` lists four registered Agent Cards.
3. Console: load the Vercel URL, sign in, click **Run sample brief**, inspect the seller lanes and the A2A Wire, then approve the award.
4. Settlement: watch the Transaction Room for the Sandbox funding → evidence → payout lifecycle.
5. PayPal: check the sandbox activity and the control plane's webhook event records.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| A service is unreachable after 15 minutes | Free-tier spin-down | Make a request to trigger spin-up; accept ~1 minute, or use a pinger (burns free hours) |
| Free services suspended | 750 monthly free instance hours exhausted | Stop services when not in use, or upgrade to paid |
| Control plane refuses to start | Sandbox guard | Confirm HTTPS `VERIFUND_PUBLIC_BASE_URL`, webhook ID, strong secrets, and sandbox PayPal host |
| Seller lane missing | Seller not activated or card not registered | Re-run the onboarding wizard; check `/v1/sellers` |
| Evidence disappears after redeploy | No persistent disk on free tier | Move evidence to object storage, or upgrade to a paid disk |
| Console cannot reach a backend service | Wrong env var or service URL | Verify the prefixed gateway URLs in the Vercel env vars |
| Checkout never reaches `FUNDED` | PayPal webhook not arriving | Confirm the webhook URL and that the control plane is public |
| Chat does not show a new seller | Console middleware hardcodes the four demo sellers | Update the seller list in the CopilotKit route |

---

## Alternative topology: paid Render + SQLite

The chosen path is the cheapest but also the most fragile: a multi-day Postgres migration, ephemeral evidence and checkpoints, cold starts, a roughly five-day monthly runtime budget, and all services public.

If the hackathon window is short and Render credits are available, the zero-code-change alternative is strongly preferable:

> **Paid Render tier (0.5c-512mb or 1c-2g) + SQLite on persistent disks + the console on Render.**

Benefits:

- No PostgreSQL migration.
- Warm services (no cold starts).
- Private networking between services.
- Shell and one-off job support for seeding.
- The evidence directory persists on a disk.

Trade-off: the console moves off Vercel/Netlify onto Render. The repository's own `docs/sponsor-integrations.md` §6 specifies this all-on-Render topology.

---

## Related documentation

- `docs/sponsor-integrations.md` §6 — the original Render topology recommendation.
- `docs/verifund-paypal-sandbox.md` — PayPal Sandbox account, webhook, tunnel, and payout setup.
- `docs/superpowers/specs/2026-11-06-verifund-neon-postgres-design.md` — PostgreSQL design (unimplemented).
- `docs/superpowers/plans/2026-11-06-verifund-neon-foundation-control-plane.md` — PostgreSQL migration plan.
- `docs/superpowers/specs/2026-11-08-dynamic-seller-onboarding-design.md` — dynamic seller onboarding design.
- `docs/runbook.md` — local operations and the legacy `make seed-demo` flow.
