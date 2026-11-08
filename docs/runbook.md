# Runbook

## Ports and health

| Service | URL | Health |
| --- | --- | --- |
| Console | <http://127.0.0.1:3000> | `/` |
| Orchestrator | <http://127.0.0.1:9000> | `/health`, `/ready` |
| Buyer | <http://127.0.0.1:9100> | `/health`, `/ready`, `/metrics` |
| Registry | <http://127.0.0.1:9105> | `/health`, `/ready`, `/metrics` |
| Northwind Audio | <http://127.0.0.1:9201> | `/health`, `/ready`, card at `/.well-known/agent-card.json` |
| CircuitForge | <http://127.0.0.1:9202> | `/health`, `/ready`, card at `/.well-known/agent-card.json` |
| Aurora Supply | <http://127.0.0.1:9203> | `/health`, `/ready`, card at `/.well-known/agent-card.json` |
| Verifund control plane | <http://127.0.0.1:9300> | `/health`, `/ready`, `/metrics` |

A quick verification:

```bash
curl http://127.0.0.1:9105/v1/sellers
curl http://127.0.0.1:9201/.well-known/agent-card.json
curl http://127.0.0.1:9100/api/runs
```

## Start and stop

```bash
make setup             # uv sync + npm install + create .env if missing
make dev               # registry, sellers, seed, buyer, console
make dev-scripted      # same, forcing deterministic mode
uv run python scripts/dev.py --verifund fake     # fake settlement stack
uv run python scripts/dev.py --verifund sandbox  # real PayPal Sandbox stack
make verifund-smoke                              # headless fake lifecycle
make down              # stop recorded process groups
```

The dev runner writes `.dev-pids.json` and logs under `.dev-logs/`. If a process dies, the
runner exits with a log tail. Remove a stale `.dev-pids.json` only after confirming no
service is listening.

## Reset and reseed

Stop the stack before touching SQLite files:

```bash
make down
make reset
make dev
```

`make seed` can be run while the stack is up. It restores each seller’s catalog stock to the
profile values and re-registers all cards. Registration is idempotent by seller ID.

## Token rotation

Development credentials live in `.env`:

- `REGISTRY_ADMIN_TOKEN` protects card registration and refresh.
- `SELLER_NORTHWIND_TOKEN`, `SELLER_CIRCUITFORGE_TOKEN`, and `SELLER_AURORA_TOKEN` protect
  each seller’s A2A endpoint.
- `BUYER_SELLER_TOKENS` maps seller IDs to the buyer’s copy of those tokens.

To rotate one seller token:

1. Change both the seller token and the matching entry in `BUYER_SELLER_TOKENS`.
2. Restart the buyer and that seller (`make down && make dev`).
3. Re-register the card only if the URL changed; card contents are fetched on refresh.

The registry never receives seller bearer tokens. The console never receives them either.

## Verifund operations

`VERIFUND_MODE` is `off`, `fake`, or `sandbox` (default `off`). The control plane
listens on `127.0.0.1:9300` only when the mode is `fake` or `sandbox`.

| Mode | Start | PayPal |
| --- | --- | --- |
| `off` | `make dev` | none |
| `fake` | `uv run python scripts/dev.py --verifund fake` | local fake checkout |
| `sandbox` | `uv run python scripts/dev.py --verifund sandbox` | real Sandbox REST + webhooks |

Logs are in `.dev-logs/verifund.log`. Health: `GET /health`; readiness:
`GET /ready`; metrics: `GET /metrics`.

```bash
curl http://127.0.0.1:9300/health
curl -H "Authorization: Bearer $VERIFUND_OPS_TOKEN" \
  http://127.0.0.1:9300/transactions
```

Common actions:

| Situation | Action |
| --- | --- |
| Capture not reflected | `POST /transactions/{id}/funding/refresh`; the reconciler also polls |
| Evidence complete, policy waiting | Wait for the inspection deadline |
| Payout stuck in `PAYOUT_PENDING` | `POST /transactions/{id}/payout` after checking the PayPal batch |
| Verification or policy failure | Reviewer `POST /release` with `override: true` and a note, except for funding mismatch, ledger inconsistency, or late capture |
| Buyer no longer wants the order | `POST /transactions/{id}/cancel` with an allowed reason |
| Refund or reversal after release | Resolve in PayPal; the transaction moves to `REVIEW_REQUIRED` |

`make reset` deletes `data/verifund.db` and `data/evidence/` along with the other
local databases. Stop the stack first.

## Common errors

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `401 unauthorized` during registration | Registry admin token mismatch | Align `REGISTRY_ADMIN_TOKEN` and restart the registry |
| Seller `401` | Buyer token does not match the seller process | Align `BUYER_SELLER_TOKENS` with the seller token |
| Card validation failure | Missing commerce extension, streaming, or bearer scheme | Inspect the seller card and `registry.log` |
| Seller timeout | Service is down or the A2A client cannot reach it | Check `/health`, logs, and `PUBLIC_BASE_URL` |
| `missing buyer credential` | Seller ID is not in `BUYER_SELLER_TOKENS` | Add the exact registry seller ID |
| `offer_expired` | Approval took longer than the offer TTL | Rerun the brief; default TTL is 30 minutes |
| `out_of_stock` | Stock was reserved by another task | Reset stock with `make seed` or use another seller |
| `database is locked` | Multiple writers or a stale stack | Stop the stack, wait, retry; keep one buyer per buyer DB |
| Registry dot offline | Registry process died | Check `.dev-logs/registry.log` |
| Live mode falls back | Missing or malformed Nebius key | Set `NEBIUS_API_KEY` and check the buyer log |
| Orchestrator not ready | Live mode without a Nebius key | Set `NEBIUS_API_KEY` or run scripted mode |

## Logs and traces

- `.dev-logs/*.log` — process stdout/stderr.
- `data/buyer.db` — run summaries and redacted A2A trace frames.
- `data/buyer-checkpoints.db` — LangGraph state and pending approvals.
- `data/registry.db` — Agent Card index and health.
- `data/<seller>.db` — offers, task state, stock, and orders.

Trace frames can be inspected through the buyer API:

```bash
curl "http://127.0.0.1:9100/api/runs/<run_id>/trace?after_seq=0"
```

Authorization and token-like fields are redacted before persistence. The UI does not show
a redaction banner.

## Manual smoke test

```bash
make dev
```

1. Confirm the header reports three healthy sellers.
2. Click **Run sample brief**.
3. Watch the three lanes move from R1 to R2; CircuitForge should be the recommended award.
4. Open **The wire** and filter inbound/outbound frames.
5. Click **Approve order** in either approval surface.
6. Confirm `Order confirmed`, an `MM-` order ID, ETA, tracking, and fulfillment timeline.
7. Start a second run and click **Reject**; confirm “No order was placed” and no order ID.

For the fake settlement flow:

```bash
make verifund-smoke
make verifund-e2e
```

For PayPal Sandbox, follow [`verifund-paypal-sandbox.md`](verifund-paypal-sandbox.md)
and then run the gated smoke:

```bash
VERIFUND_SANDBOX_SMOKE=1 make verifund-sandbox-smoke
```

To exercise live mode:

```bash
NEBIUS_API_KEY=<your-nebius-key> MARKETMESH_LLM_MODE=live make dev
```

Then verify the buyer trace contains planner decision events and that ranking still matches
the deterministic totals. Do not expect non-deterministic prices from the model.

## Docker

```bash
docker compose up --build
```

The same ports are published to localhost. The Compose network uses service DNS names for
card URLs and buyer-to-seller traffic. `docker compose down -v` also removes the shared data
volume.

## Safe operating limits

This is a single-user local prototype. Do not bind it to a public interface, reuse the
development tokens outside localhost, or treat the approval receipt as verified identity.
There is no live payment processing, real fulfillment, tenant isolation, or
production secret management in this codebase. Verifund moves PayPal Sandbox
funds only and is disabled by default.

## Onboarding a seller after `make dev`

1. Open http://127.0.0.1:3000/seller/onboarding (Clerk org) or set `MARKETMESH_DEV_IDENTITY=fake` for local/CI.
2. Walk steps: profile → create agent → config → catalog import (JSON/YAML, examples in `docs/templates/`) → test → verification + payout email → activate.
3. The seller appears in the buyer marketplace within 30 s (registry poll).
4. For the legacy 4-seller demo: `make seed-demo` (requires a running stack).
