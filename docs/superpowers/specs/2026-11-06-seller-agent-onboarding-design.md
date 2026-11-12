# Verifund Seller Agent Onboarding — Design (stub)

Date: 2026-11-06
Status: Stub; scope and open questions only. Not ready for implementation.
Related specs:
- `docs/superpowers/specs/2026-11-06-verifund-multi-tenancy-design.md` (authority for tenancy, status axes, and tables)
- `docs/superpowers/specs/seller-agent-onboarding-recommendation.md` (source recommendation)

## 1. Purpose

This document will define the seller-facing workflow that the tenancy design
deliberately leaves out: the wizard, commerce integrations, catalog and inventory, the
policy editor, the test console, and seller notifications. It builds on the tables and
state machines in the tenancy spec and must not restate or contradict them.

## 2. What this spec owns

| Area | Notes |
|---|---|
| Onboarding wizard UX | Seven steps, resumable, backed by `seller_onboarding` |
| Commerce integrations | Shopify, WooCommerce, CSV, manual; credentials by reference |
| Catalog and inventory | Tenant-owned schema, sync, and freshness rules |
| Policy editor | Writes to the seller agent's store; returns version and hash |
| Test console | Runs the minimum checks and displays results |
| Seller notifications | Post-agreement guidance and evidence reminders |
| Onboarding analytics | Step drop-off; no tenant-identifying data in aggregates |

## 3. What the tenancy spec already fixes

- Tables: `seller_onboarding`, `seller_onboarding_events`, `seller_verifications`,
  `seller_integrations`, `agents`, `agent_test_runs`, and `agent_credentials` (control
  plane).
- Status axes and capability matrices (§9.2–9.5 of the tenancy spec).
- Provisioning sequence and policy drift (§12.4–12.5).
- Authorization: business organization only, `org:admin` to start onboarding,
  `org:agents:manage` for agents.
- Decisions 20–26.

## 4. Minimum test set for activation

| Check | Pass condition |
|---|---|
| Agent authentication | Credential verifies and the agent is `active` |
| Catalog retrieval | A known SKU is returned for the organization |
| Pricing bounds | Offers below the floor and above the ceiling are refused |
| A2A communication | A mediated test call returns a valid offer |
| Authority restriction | An action above the agent ceiling requires approval |
| Revocation | A revoked credential stops working within the cache TTL |

## 5. Open questions

1. Integration credential storage: which secret manager, and what rotation policy?
2. Catalog sync: push webhook or pull on demand, and what staleness is acceptable?
3. Policy editor conflicts: what happens when two admins edit concurrently — version
   check, or last-write-wins with audit?
4. Test console isolation: does it run against a sandbox seller agent or the live one
   with a test flag?
5. Onboarding abandonment: after how long is an `in_progress` organization nudged or
   cleaned up?
6. Notifications: in-console only, or email and Slack through `seller_integrations`?
7. Evidence drafting: which agreement clauses generate the checklist, and who signs off?

## 6. Non-goals

- Tenancy, membership, roles, or authorization changes (tenancy spec).
- Agent lifecycle transitions (tenancy spec §9.4).
- Payments and payout release (tenancy spec §13).
- Buyer-side onboarding.

> Implemented by plan
> `docs/superpowers/plans/2026-11-06-seller-onboarding-agent-configuration.md`
> (Appendix B of `docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md`).
