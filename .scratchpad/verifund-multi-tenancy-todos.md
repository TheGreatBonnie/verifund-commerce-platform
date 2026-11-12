# Verifund Multi-Tenancy Execution (M0-M8) — inline on feat/verifund-multi-tenancy-implementation

- [x] M0 T1: Clerk provider + sign-in/up routes + env
- [x] M0 T2: bare middleware + console-session helper
- [x] M0 T3: console shell guard + org switcher
- [x] M0 T4: controlPlaneForUser + agreement actions
- [x] M0 T5: sweep routes + remove demo identities
- [x] M1 T6: tenancy schema + repository
- [x] M1 T7: rebuild audit_log + webhook source
- [x] M1 T8: Clerk webhook ingestion (Svix)
- [x] M1 T9: apply Clerk events to mirror
- [x] M1 T10: onboarding + verification state machine (service)
- [x] M1 T11: backfill + demo seed
- [x] M2 T12: Clerk session verification + Identity
- [x] M2 T13: identity resolution + lazy Clerk sync
- [x] M2 T14: TenantScope + tenant-scoped reads
- [x] M2 T15: platform-admin + verification endpoints + onboarding routes
- [x] M3 T16: tenant columns + backfill core records
- [x] M3 T17: require_transaction + action permissions
- [x] M3 T18: counterparty visibility matrix
- [x] M3 T19: seller gate (award/tokens/invitations)
- [x] M3 T20: isolation suite
- [x] M4 T21: seller-access from Clerk
- [x] M4 T22: onboarding entry routing + wizard shell
- [x] M4 T23: invitation -> Clerk redirect
- [x] M4 T24: remove staff seller cookie
- [x] M5 T25: agent/credential/test-run tables
- [x] M5 T26: credential issuance + verification
- [x] M5 T27: provisioning + policy drift
- [x] M5 T28: activation test gate
- [x] M5 T29: registry projection + card URL ownership
- [x] M5 T30: agent audit + fulfillment:assist
- [x] M6 T31: payment_accounts + payout resolution
- [x] M6 T32: payout releases + reconciler condition
- [x] M6 T33: tenant-prefixed evidence
- [x] M6 T34: system principal + worker attribution
- [x] M7 T35: runs tenant columns + console runs API
- [x] M7 T36: checkpoint thread IDs + memory namespace
- [x] M7 T37: SSE + streaming authorization
- [ ] M8 T38-40: GATED — Postgres + RLS (do not ship with M0-M7)

Legend: executing-plans + test-driven-development + clerk-nextjs-patterns + clerk-orgs + clerk-webhooks + clerk-setup.
M8 stays behind VERIFUND_TEST_POSTGRES_URL / explicit gate.
