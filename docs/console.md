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

## Admin workspace

Platform-admin-only area (top-level `/admin` layout, see
`docs/superpowers/specs/2026-11-21-admin-workspace-design.md`):

- `/admin` — overview (pending verifications, platform transaction count, held funds).
- `/admin/transactions`, `/admin/transactions/[id]`, `/admin/transactions/[id]/audit`
  — platform transactions, ledger/detail/event view, and per-transaction audit.
- `/admin/payouts` — funded-queue view with an approval action that posts to
  `/v1/admin/transactions/{id}/payout-release`.
- `/admin/disputes`, `/admin/disputes/[id]` — read-only dispute views.
- `/admin/verification` — pending seller verifications.
- `/admin/users` — read-only Clerk user list (no promote/demote controls).
- `/admin/audit`, `/admin/settings` — global audit log and redacted platform settings.

Access is additive: a Clerk admin keeps buyer/seller access and also sees an
Admin link in those headers. Admin authority comes only from a verified Clerk
session whose `publicMetadata.role` is mirrored into the control plane's
`platform_admins` table by the verified Clerk webhook. Granting or revoking the
role is an out-of-band Clerk Dashboard operation — there is no in-app
promotion or demotion. Non-admins requesting `/admin` are redirected to `/`,
and `/v1/admin/*` returns 403.

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