# Console (Next.js)

Routes (all under the `(console)` layout with sidebar + thread drawer):

- `/` — home: live run (ConsoleShell), recent runs, registry health.
- `/runs` — run history from the buyer API.
- `/runs/[runId]` — run detail/replay: deal room + A2A wire.
- `/sellers` — registry sellers directory.
- `/settings` — console settings + reset local state.
- `/help` — usage guide and glossary.

Seller workspace (separate layout, see `docs/seller-fulfillment-workspace.md`):

- `/seller/dashboard`, `/seller/orders`, `/seller/fulfillment`,
  `/seller/fulfillment/[id]`, `/seller/fulfillment/[id]/evidence`,
  `/seller/fulfillment/[id]/activity`, `/seller/evidence`, `/seller/payouts`.
- `/fulfillment/access/[token]` — invitation exchange.

API proxies: `POST /api/seller/transactions/[id]/evidence`,
`POST /api/seller/transactions/[id]/dispute-evidence`,
`GET /api/seller/transactions/[id]/evidence/[evidenceId]`.

## Development

```bash
cd apps/console
pnpm install
pnpm run dev
pnpm run test
pnpm run typecheck
pnpm run test:e2e
```

## Notes

- Runs are authoritative from the buyer REST API (`/api/runs`, `/api/runs/:id`); the
  console only adds thin proxy routes.
- No mock data ships with the console.