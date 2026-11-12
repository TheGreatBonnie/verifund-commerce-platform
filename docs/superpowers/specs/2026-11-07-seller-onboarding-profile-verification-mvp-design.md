# Seller Onboarding — Profile & Verification MVP (Wizard Unblock)

**Date:** 2026-11-07  
**Status:** Approved design (brainstormed) — not yet implemented  
**Scope:** Complete the **incomplete seller onboarding wizard steps** (`profile`, `verification`) in the seller workspace so a seller can progress end-to-end in sandbox, without implementing full KYC or in-console admin review.

## Context

The seller onboarding wizard lives at `apps/console/app/(seller-onboarding)/seller/onboarding/*` with step order `profile → verification → integrations → agent_setup → policies → testing → activation` (`apps/console/lib/onboarding.ts`, `components/seller-agent/OnboardingStepper.tsx`). Entry routing (`onboarding/page.tsx` + `sellerEntryPath`) auto-starts onboarding via the control plane and redirects by `profile.verification_status` / `onboarding.current_step`.

**Implemented (agent-config slice, Appendix B / `2026-11-06-seller-onboarding-agent-configuration.md`):** `integrations` (catalog import), `agent_setup`, `policies`, `testing`, `activation` wizard pages/components/actions; control plane `POST/PATCH/GET /v1/agents*`, `POST /v1/seller/catalog/import`, `POST /v1/agents/{id}/test|activate`; seller runtime `/internal/agent-configs`, `/internal/catalog/import`, `/internal/test-suite`; `/seller/agent` edit-in-place workspace. (Note: `docs/.../specs/seller-agent-config-seller-onboarding.md` is superseded/provenance.)

**Incomplete (this design):**
- **`profile`** — no `profile/` page; `/seller/onboarding/profile` renders the stub ` [step]/page.tsx`. Backend seeds profile/onboarding (`POST/GET /v1/seller/onboarding`, `onboarding/service.create_onboarding`, `in_progress/profile`).
- **`verification`** — no `verification/` page (stub). Backend supports `POST /v1/seller/verification/submit` and admin decision logic (`onboarding/service.decide_verification`; ops `POST /ops/sellers/{seller_id}/verification` in `tenancy/routes.py`, platform-admin gated), but the console wizard has no submit UI/action and no in-console review UI. Activation requires a verified seller (`activation/page.tsx` + CP activation gate), while `sellerEntryPath` keeps unverified sellers in onboarding — blocking first-time end-to-end completion.

## Goals / Non-goals

**Goals (MVP unblock, Approach A)**
1. Functional `profile` and `verification` wizard pages wired to control-plane, server-authoritative operations.
2. **Profile:** confirm + minimal edits (at minimum `display_name`, within existing schema) persisted; advance `current_step` to `verification`.
3. **Verification:** submit from wizard; in **sandbox** (`settings.is_sandbox` / `VERIFUND_MODE=sandbox`) auto-approve server-side so the seller becomes `verified` and can proceed to activation. Non-sandbox: submit → `pending/awaiting review` (approval out-of-band).
4. Preserve existing tenancy/auth patterns, state machine validity, and all existing tests.

**Non-goals**
- Full KYC: document/evidence upload, storage, OCR, identity verification providers.
- In-console admin/reviewer decision UI.
- Rich business profile schema beyond minimal fields already supported.
- Changes to agent-config activation logic beyond being unblocked by verification.

## Approach

**Approach A (approved): minimal, authoritative CP changes + console wizard pages/actions.** Profile and verification transitions are enforced in the control plane; the console orchestrates only via authenticated calls. (Rejected for MVP: console-driven orchestration that splits transitions across ops/admin calls; full KYC foundation.)

## Section 1 — Control plane: data/API & state transitions

### 1.1 Profile save + advance
**Add:** `POST /v1/seller/onboarding/profile` in `apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py` (service helper in `onboarding/service.py` as needed).
- **Auth:** `require_identity(request)`; org/tenant only from verified identity (never body).
- **Body:** minimal Pydantic model, e.g. `display_name: str` (constrained length). Confirm exact persisted fields against `tenancy/repository.py` / `seller_profiles` schema before implementation (`upsert_seller_profile` exists).
- **Behavior:** load profile for `identity.tenant_id` (404 if missing / wrong context). `store.upsert_seller_profile(organization_id, seller_id, display_name)` (keep `seller_id` stable). Advance onboarding via `store.upsert_onboarding(organization_id, status="in_progress", current_step="verification")` **idempotently and non-regressively** (do not move back from submitted/verified/terminal states). `record_audit` (`seller.onboarding.profile_saved`, scope organization, actor user). Return `{ profile, onboarding }`.

### 1.2 Verification submit + sandbox auto-approve
**Modify:** `POST /v1/seller/verification/submit` (`onboarding/routes.py`, `onboarding/service.py::submit_verification`) using `request.app.state.settings`.
- Keep existing submit behavior/validation: allowed from `SUBMIT_FROM={"unverified","rejected"}`; records submission, sets `pending` and onboarding `submitted/verification` (audited).
- **Sandbox auto-approve (server-gated only):** if `settings.is_sandbox` is true and transition is valid, perform the approval server-side in the same logical flow by invoking `decide_verification(..., decision="verified", note="Auto-approved in sandbox", reviewer_user_id=<aligned with audit conventions; system/acting marker>)`. This follows `DECIDE_MAP` (`verified` from `pending`) and emits `seller.verification.approved`. Set onboarding to an unblocked state (recommend `status="in_progress", current_step="activation"` or `agent_setup`; informational because `sellerEntryPath` routes verified profiles to `/seller/dashboard`).
- **Non-sandbox:** no auto-approve; return `pending/submitted` and UI shows awaiting out-of-band review.
- **Idempotency/edges:** invalid states → `409`; never double-decide. Resubmit allowed for `rejected` per state machine.

## Section 2 — Console: wizard pages & server actions

**Add static routes (override `[step]`):**
- `apps/console/app/(seller-onboarding)/seller/onboarding/profile/page.tsx`
- `apps/console/app/(seller-onboarding)/seller/onboarding/verification/page.tsx`
Keep `[step]/page.tsx` fallback.

**Patterns:** `auth.protect()`, `dynamic="force-dynamic"`, `<OnboardingStepper />`, load via `loadAgentContext()`/`controlPlaneForUser("/v1/seller/onboarding")`, unreachable `<Panel>`/`<Alert>` as in existing steps. Mutations in `.../onboarding/actions.ts` (`"use server"`, `auth.protect()`, `controlPlaneForUser`, `revalidatePath("/seller/onboarding")`).

### 2.1 Profile
- Server page prefilled from `profile.display_name`/name.
- Client form (e.g. `components/seller-agent/ProfileForm.tsx`): required `display_name`, optional read-only seeded info; `saveProfileAction` → `POST /v1/seller/onboarding/profile`; on success navigate to `/seller/onboarding/verification` (or `sellerEntryPath` result); disable during submit; show CP errors.

### 2.2 Verification
- Client form (e.g. `VerificationSubmitForm.tsx`) + server page state rendering:
  - `unverified`/`rejected`: minimal submission (confirmation and/or short reference/notes mapped to `VerificationSubmit.documents` — list|dict per `onboarding/routes.py:16-18`; **no file upload**) → `submitVerificationAction` → `POST /v1/seller/verification/submit`.
  - `pending` (non-sandbox): “Awaiting review” (no resubmit).
  - `verified` (incl. sandbox auto-approve response): success + explicit CTA to continue setup (`/seller/onboarding/agent_setup` or `/seller/agent`), not relying on entry redirect.
- Non-sandbox messaging states approval is out-of-band/admin.

### 2.3 Routing
- Stepper links unchanged. `sellerEntryPath` remains authoritative; verified → `/seller/dashboard` (`lib/onboarding.ts:16`). Direct access to profile/verification when already verified renders a benign continue/verified state.

## Section 3 — State/routing, edge cases, security & tenancy

- **Transitions:** CP-validated, non-regressive profile advance; verification obeys `SUBMIT_FROM`/`DECIDE_MAP`; sandbox auto-approve only via server settings.
- **Audit:** `seller.onboarding.profile_saved`, existing `seller.verification.submitted`, plus `seller.verification.approved` on sandbox auto-approve (clear note/actor).
- **Resilience:** double-submit guarded in UI and by CP `409`; refresh-safe; CP unreachable → friendly panels. Profile/verification are CP-only (no seller-runtime dependency).
- **Security/tenancy:** `require_identity` everywhere; org from identity only; `auth.protect()` + `controlPlaneForUser`; auto-approve never client-controlled. Input length/shape validated by Pydantic.
- **Compatibility:** no breaking changes to agent-config steps/APIs; payload shapes remain `{profile,onboarding}` compatible.

## Section 4 — Testing, verification, rollout

**Control plane (pytest):** profile save/advance/idempotency/non-regression/404-wrong-context; verification submit pending (non-sandbox), sandbox auto-approve to verified with correct audits/state, 409 invalid state, auto-approve gated by sandbox mode. Run targeted then `uv run pytest`.

**Console (vitest):** `tests/lib/onboarding.test.ts` coverage as needed (profile/verification/current_step routing, verified→dashboard already present).

**Manual sandbox E2E:** entry auto-creates → profile save advances to verification → submit auto-verifies → continue to `agent_setup/policies/testing/activation` (now unblocked) → verified entry/dashboard and `/seller/agent`. Confirm non-sandbox pending messaging path and unreachable error panels.

**Rollout:** expect no schema migration (reuse existing profile/onboarding fields — confirm). No new flag required (uses `VERIFUND_MODE`/`is_sandbox`). Document MVP limits: no file upload/KYC, no in-console admin review, minimal profile fields, verified entry routes to dashboard (explicit CTAs provided).

## Implementation checklist (for planning)

- [ ] CP: profile save+advance endpoint/service + audit; confirm repo fields.
- [ ] CP: sandbox auto-approve in verification submit path (server-gated) + onboarding unblocked state + audits.
- [ ] CP: tests for transitions, 409s, sandbox gating.
- [ ] Console: `profile/page.tsx`, `verification/page.tsx`, client forms, `onboarding/actions.ts` (`saveProfileAction`, `submitVerificationAction`).
- [ ] Console: states (unverified/rejected/pending/verified), errors, CTAs, `revalidatePath`/navigation.
- [ ] Console: routing/helper tests as needed.
- [ ] Manual sandbox E2E + full `uv run pytest` green.
- [ ] Docs note (README/onboarding spec addendum) for MVP behavior.
