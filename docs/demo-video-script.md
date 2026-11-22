# Verifund (MarketMesh + Verifund settlement) — Hackathon demo video script (production guide)

> **Status:** Script + production guide (written for the `deploy/render` backend + `deploy/console` frontend deployed as described below).  
> **Audience/length (per user selection):** **~6 minutes** technical-but-accessible judge walkthrough (longer than the repo’s 3-minute outline in `docs/sponsor-integrations.md`; that file remains a shorter narrative reference).  
> **Primary through-line (per user selection):** **Buyer query:** *“find me a good laptop for programming under $1500”* in the deployed console chat — discovery → sourcing mandate (HITL) → A2A mediation/negotiation handoff → award (HITL, if reached) → Verifund settlement path (agreement/funding/PayPal Sandbox/evidence/release/receipt), with the older headset/Channel3 story used only as optional B-roll/supporting context.

---

## Decisions locked (from your answers)

| Q | Decision |
|---|----------|
| Q1 | **~6-minute deep dive** (not the 60s teaser, not the repo’s default 3-minute script). |
| Q2 | **Laptop query as spine.** Headset scenario from README/examples is B-roll only if needed for continuity. |
| Q3 | **Keep real on-screen names:** “**MarketMesh**” (exchange/console surface) and “**Verifund**” (trust/settlement layer). Add one lower-third on first combined appearance: **“MarketMesh exchange · Verifund settlement authority”** (do not fake a full rebrand). |
| Q4 | **All-live, single take** (preferred). Record the full flow live on the deployed console in one session if possible. Be prepared to edit out pauses; if anything breaks, the **verification checklist** below tells you how to re-test and what to say on camera (do not claim live money). Label modes explicitly when visible (e.g. **Sandbox / fake / off** and **“no live funds”**). |
| Q5 | **Clean in edit:** hide/collapse raw **“Thought for…”** reasoning panels; avoid the comparison table’s **“—” best-price column** (crop tighter, or narrate over it, or zoom product cards) — do **not** show that bug as a feature; cut the **stalled Aurora mediation tail** if it repeats. |
| Q6 | This file is the **deliverable** (script + production guide).

---

## Honesty & disclaimers (say/read these on screen or in VO)

- **No live money.** Verifund demo uses **PayPal Sandbox** (or **fake/off** modes depending on deployment) — state **“Sandbox mode · no live funds”** when showing checkout/funding.
- **Agents, not magic.** Buyer/orchestrator use LLM + tools (Nebius in live mode on Render per repo config); retrieval is semantic + hard filters over the marketplace catalog (code does ranking/filtering rules; the agent presents results).
- **Human-in-the-loop is real.** Before orders/settlement-critical steps the UI shows approval/confirmation cards (award, sourcing mandate, Verifund funding/release flows as applicable).
- **Demo is production-shaped, not production.** From `README.md`: seeded catalogs, simulated verification in some paths, demo identities, etc., as documented.
- **Known rough edges (acknowledge if shown):** raw chain-of-thought may appear in UI if not hidden in edit; the laptop comparison table can show **“—”** in price cells in some renders — **edit around it**.
- **Do not say “AI picks the winner.”** Say: **“Code computes ranking and eligibility; a person approves the final order.”**

---

## What you are filming (verified facts)

### Deployed surfaces (from repo: `render.yaml`, `docs/deployment-guide.md`, `docs/sponsor-integrations.md`)

| Piece | URL / role (as configured) |
|-------|----------------------------|
| Console (Vercel) | `https://verifund-console.vercel.app` (documented). Repo copy says “MarketMesh — open agent exchange” in UI/root metadata. |
| Merged gateway (Render) | `https://gateway-795m.onrender.com` (Render service `gateway`). Prefixes (typical): `/orchestrator`, `/buyer`, `/registry`, `/sellers`, `/control-plane`, `/verifund-agent` (see `render.yaml`, deployment docs). |
| Orchestrator AG-UI | Reached via console CopilotKit runtime → Next.js `/api/copilotkit` → orchestrator AG-UI (default local `http://127.0.0.1:9000`; deployed via gateway path per env). |

### Console stack (for on-screen description, optional VO line)

- **Next.js 16 (App Router), React 19, TypeScript**, Tailwind + custom “MarketMesh” styling, **Clerk** auth, **CopilotKit** chat (`@copilotkit/react-core/runtime`), AG-UI middleware to orchestrator, optional **PayPal JS SDK** (`@paypal/react-paypal-js`) when Verifund sandbox/embedded flows are used. (From console explorer report.)

### How chat works (technical accuracy)

- User types in chat at **`/chat`** (`apps/console/features/chat/chat.tsx`). The UI uses **CopilotKit** with `agentId="marketmesh_orchestrator"`.  
- Console calls its own **`/api/copilotkit`** (Next route `apps/console/app/api/copilotkit/[[...slug]]/route.ts`), which is protected by **Clerk** (`auth.protect()`), then proxies/orchestrates to the **orchestrator AG-UI** and mediates A2A sellers/buyer context per server logic (see `route.ts`, `agent.ts`).  
- Orchestrator (`apps/orchestrator_agent/orchestrator_agent/server.py`) exposes AG-UI at **`/`** on its service and `/health`, `/ready`; tools include **`search_marketplace_products`**, **`present_product_recommendations`**, **`mediate_seller_call`**, and Verifund tools when enabled.

### Marketplace discovery (for VO: “what happens when I ask for a laptop under $1500”)

From backend explorer + code paths:

- Orchestrator instruction: for “find/search/browse” use **`search_marketplace_products`**. “under $1500” → **`max_unit_price_cents=150000`** (per-unit). `category="laptop"` resolves via taxonomy to **Laptop + MacBook** (so MacBooks included). `use_case`/`preferences` guide ranking contextually; **hard filters** are category/resolved categories, price ceiling, stock rules as specified. If user wants availability now, `in_stock_only=true` may be set per instruction (depends on agent reasoning shown).  
- Retrieval: semantic search over aggregated marketplace products (Nebius embeddings in live path when configured) + deterministic browse fallback; results shaped by `commerce_core.retrieval` / orchestrator `marketplace.py` (returns `applied_filters`, `total_candidates`, `products[]`, optional retrieval trace).  
- **Live test (2026-11-22, recorded during prep):** query *“find me a good laptop for programming under $1500”* returned **7 laptop candidates** with a comparison table rendered by **`present_product_recommendations`**-style UI in chat (product cards + “Ask agent to negotiate” on cards). Orchestrator also showed internal reasoning text in the transcript during that run (hide in edit per Q5).

### Sourcing mandate (HITL) — what viewers see

- Before Buyer handoff, orchestrator may trigger **frontend HITL** `request_sourcing_mandate` (rendered as **`SourcingMandateCard`** in console). Live test showed fields like quantity, budget ceiling/target, currency, deadline, warranty/returns, must-haves, plus locked product/offers context. User confirms via **“Confirm & send to Buyer”** (or cancel). This is the “human stays in control of mandate” beat.

### Buyer agent (A2A) and mediated calls (conceptual, for VO)

- Buyer service is a LangGraph app (`apps/buyer_agent/buyer_agent/graph.py`): interprets brief, discovers/plans sourcing, mediates seller calls via orchestrator’s **`mediate_seller_call`** (orchestrator calls buyer internals with tokens), ranks offers deterministically, interrupts for **award approval** (`reason="order_approval"`, `await_approval`) when offers exist — **code computes winner**; human approves. Settlement/off-mode paths branch after approval (see `graph.py`, `docs/workflow.md`).  
- In the live test, after confirming mandate the flow moved toward Buyer handoff and then showed **mediated seller call** messaging (e.g. “mediate the call to Aurora Supply…”). The run **did not reach a visible award approval card** within the observed window (stalled in that session) — **do not show the stalled tail**; cut to the next prepared beat (award card from a clean run/screenshot/video clip you recorded separately, or proceed to the scripted settlement walkthrough using Transaction Room/fixtures as labeled).

### Verifund lifecycle (what to show if you reach it, and what to say)

- **Verifund agent** (`apps/verifund_agent`) + **control plane** (`apps/verifund_control_plane`) coordinate: agreement review/approval, funding approval, **PayPal embedded checkout / funding** in sandbox contexts (UI components like `AgreementApprovalHitlCard`, `FundingApprovalCard`, `PayPalCheckoutCard` per console report), evidence collection/wait, **release approval** (HITL), receipt.  
- **State model (high level):** `AWARDED → AGREED → FUNDING_PENDING → FUNDED → FULFILLMENT_PENDING → … → RELEASED` with review/dispute branches (`domain.py`).  
- **PayPal:** sandbox via `paypal/sandbox.py` (OAuth, orders capture, payouts, webhook verify) + fake checkout routes in control plane; webhooks at `/webhooks/paypal`, Clerk webhook at `/v1/webhooks/clerk`.  
- **Always label:** **“Verifund mode: … (from env). PayPal Sandbox — no live funds.”** (Check deployment: `render.yaml` shows `VERIFUND_MODE=sandbox`, embedded checkout flags; your live console may differ.)

### Sample data note (important)

- Repo README sample brief is **headset** (Nimbus NC-700). Your video spine is the **laptop** query — that is fine; explain: “This is a team laptop procurement flow in the same MarketMesh pipeline.”  
- **Channel3:** mentioned in `docs/sponsor-integrations.md` as planned; **no Channel3 implementation in scanned app code** — **do not claim live Channel3 enrichment** in this video.

---

## 6-minute run-of-show (timecoded)

> Adjust ±10–15 seconds as needed. VO is concise; show UI, not walls of text.

### Beat 1 — Cold open + problem (0:00–0:35)
**On screen:** Title card: “Verifund — Trust infrastructure for agentic commerce” (optional). Then console landing page `verifund-console.vercel.app` (MarketMesh home).  
**Lower-third (once, when introducing layers):** “MarketMesh exchange · Verifund settlement authority.”  
**VO:** “AI agents can find products and negotiate deals—but negotiating isn’t the same as trust. Verifund adds the missing layer: human-approved agreements, verifiable fulfillment evidence, and PayPal Sandbox settlement you can audit—before any order becomes final.”

### Beat 2 — Log in / context (0:35–0:55)
**On screen:** Show Clerk sign-in/session state briefly if visible (or jump into `/chat` if already signed in).  
**VO:** “I’m signed into the console as a buyer. From here, I describe what my team needs in plain language.”  
**Note:** Do not show real secrets or admin panels unless essential.

### Beat 3 — The spine query: laptop under $1500 (0:55–1:25)
**On screen:** Navigate to **Chat** (`/chat`). Type (or paste):  
`find me a good laptop for programming under $1500`  
**Edit:** Hide/collapse any **“Thought for…”** panels in the final cut (show the user message + agent’s final summary/cards).  
**VO:** “I ask the assistant: find me a good laptop for programming under fifteen hundred dollars. The orchestrator uses marketplace search with hard limits—like a per-unit ceiling of fifteen hundred—and semantic matching to surface relevant laptops, including MacBooks in this catalog.”

### Beat 4 — Discovery results + comparison (1:25–2:25)
**On screen:** Show product cards / **“Searching Marketplace…”** state briefly, then results (from live test: 7 candidates). Show the comparison/recommendation UI.  
**Editing:** Crop or zoom to avoid the **“—” best-price column** bug if it appears; narrate prices from the cards/recommendation text instead.  
**VO:** “The agent returns a ranked set of options with rationales—no raw model scores shown to the buyer. I can inspect cards and ask it to negotiate for a specific pick.”  
**Callout text overlay (optional):** “Hard filters: category + price ceiling (code). Ranking signals: semantic + availability/rating cues (agent-guided).”

### Beat 5 — “Ask agent to negotiate” → sourcing mandate HITL (2:25–3:20)
**On screen:** Click **“Ask agent to negotiate”** on **MacBook Air M2** (or the model you chose in the live take). Show the **Sourcing Mandate** card: locked product/offers, quantity, budget ceiling, currency, deadline, warranty/returns, must-haves. Fill example values consistent with a real demo (e.g. qty 1, budget $1500, currency USD, warranty/returns note, must-haves like 16GB RAM / 512GB SSD / 13"). Click **“Confirm & send to Buyer.”**  
**Edit:** Cut long waits; you may speed up with tasteful time-lapse + VO.  
**VO:** “Before handing off to the Buyer agent, the console collects a confirmed mandate. I lock quantity, budget ceiling, delivery preferences, warranty expectations, and must-have attributes. Nothing proceeds to negotiation without this explicit confirmation.”

### Beat 6 — A2A negotiation (mediated) — show success, cut failure (3:20–4:15)
**On screen:** Show messages indicating the Buyer is coordinating with sellers via **A2A mediation** (orchestrator tool `mediate_seller_call`). If your single take reaches an **award approval card** (`ApprovalCard` / award HITL), show it: recommended seller, landed total, score, mandate checks, **Approve order / Reject**, note field.  
**If the take stalls** (as observed: stopped around mediating Aurora Supply), **do not show the stall.** Instead:  
- Option A (preferred for Q4 “all-live” intent if you re-run): do a second live run that completes to award approval and splice it in (label splice in voice: “in this run…” is fine if honest).  
- Option B: show a **previously recorded** clean award-approval clip or screenshots in order with VO: “In a successful run, the Buyer compares offers and the system presents an award for human approval—code ranks, you decide.”  
**VO (success path):** “The Buyer agent negotiates with independent seller agents over A2A. Offers are evaluated against the mandate; the ranking is computed by code. I still make the final call.”  
**Callout:** “**Human checkpoint required** before any order is placed.”

### Beat 7 — (If shown) Award approved → Verifund path overview (4:15–4:50)
**On screen:** After approval (or in walkthrough), show the transition into Verifund-linked steps if present: agreement review cards, funding approval, etc., as they appear in your build.  
**VO:** “With the award approved, settlement moves into Verifund: structured agreement, funding approval, and PayPal Sandbox checkout when enabled—separating negotiation from money movement.”

### Beat 8 — PayPal Sandbox / funding (4:50–5:25)
**On screen:** Show **`PayPalCheckoutCard` / funding approval** UI if reached. Clearly show **environment: Sandbox** and/or **“no live funds”** overlay text you add in edit. If using embedded PayPal buttons, show the flow up to the point safe for recording (do not expose real account emails unnecessarily).  
**VO:** “In Sandbox mode, funds flow through PayPal’s test environment. Verifund coordinates the order/funding steps; I must explicitly approve before release actions proceed. No live money is involved.”

### Beat 9 — Evidence → release → receipt (5:25–5:50)
**On screen:** Use **real Transaction Room / settlement UI** from a seeded or completed run if the live chat did not complete: show evidence checklist/wait states, release approval card conceptually, and **receipt/proof** view. (Label: “Recorded from a verified Sandbox/test run.”)  
**VO:** “Sellers submit evidence against agreed requirements. Verifund tracks verification and gates release behind another human approval, then produces a receipt/audit trail tied to the transaction.”

### Beat 10 — Close (5:50–6:00)
**On screen:** Back to console dashboard or a summary slide: “MarketMesh exchange + Verifund settlement authority.” Links in description: repo/docs.  
**VO:** “MarketMesh brings competitive, agent-to-agent negotiation with auditable guardrails. Verifund is the trust layer that turns agreements into accountable, human-approved settlement.”  
**End card:** “Demo: PayPal Sandbox, no live funds. Code: [your repo URL].”

---

## Shot list (checklist)

- [ ] Console home (`verifund-console.vercel.app`) — 5–10s establishing.
- [ ] `/chat` empty state (placeholder visible) — 2–3s.
- [ ] Type and submit: “find me a good laptop for programming under $1500”.
- [ ] “Searching Marketplace…” / loading state.
- [ ] Product cards grid (at least MacBook Air M2 visible).
- [ ] Comparison/recommendations panel (cropped to avoid “—” if present).
- [ ] Click “Ask agent to negotiate” on chosen product.
- [ ] Sourcing Mandate card filled + “Confirm & send to Buyer” clicked.
- [ ] Mediated/A2A progress messages (if clean) — short.
- [ ] Award approval card (Approve/Reject visible) **or** B-roll of known-good clip.
- [ ] Verifund agreement/funding cards (if reached).
- [ ] PayPal Sandbox checkout UI (labeled).
- [ ] Transaction/receipt or evidence timeline from a completed test run (labeled).
- [ ] Close card.

---

## B-roll / fallback assets (recommended)

- Screen recording of a **clean seeded run** that reaches award approval and/or Transaction Room (so you can splice if all-live stalls).
- `docs/sponsor-integrations.md` three-minute outline and diagrams (for optional cutaway slides) — do **not** overuse headset story except one sentence of context if needed.
- `README.md` / `docs/workflow.md` architecture diagrams (exported PNG) for a quick “under the hood” flash if desired (keep under ~10 seconds total extra).

---

## Production checklist

- [ ] Use a **clean browser profile** (no devtools clutter, notifications off).
- [ ] Set system/display to **consistent resolution** (1080p recommended); hide bookmarks bar.
- [ ] Verify env before recording: console points to deployed gateway/orchestrator as intended; **Clerk** logged in as a demo buyer account.
- [ ] Test the exact query once in a practice run; note timings.
- [ ] Record **room tone** / silent buffer at start/end for easier editing.
- [ ] Add **lower-third** once: “MarketMesh exchange · Verifund settlement authority”.
- [ ] Add **on-screen labels** when showing settlement: “PayPal Sandbox — no live funds”, “Mode: sandbox/fake as applicable”.
- [ ] In edit: remove “Thought for…” blocks, cut stalled mediation repeats, speed up dead air (max ~1.5× sparingly).
- [ ] Export with clear audio; normalize levels.

---

## Verification checklist (re-test before final export) — including browse MCP

### A. Manual browser smoke (deployed)

1. Open `https://verifund-console.vercel.app` → sign in (Clerk). Confirm role is buyer/context as expected.
2. Go to **`/chat`**.
3. Send: `find me a good laptop for programming under $1500`.
4. Confirm: product cards appear, recommendation/comparison UI appears. **Do not** narrate the “—” bug as real data; if it appears, plan the cut.
5. Click **“Ask agent to negotiate”** for a laptop (e.g. MacBook Air M2). Confirm **Sourcing Mandate** card appears; fill and submit. Confirm handoff messages toward Buyer/A2A mediation appear.
6. If **award approval** appears: capture it. If not: stop recording that branch cleanly and use fallback clip.

### B. Re-test using OpenCode browse MCP (optional, matches how this script was drafted)

From the repo root (`/Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a`), an agent with browse tools can:

1. `tools.browse.status()` → ensure connected.
2. `tools.browse.navigate({url: "https://verifund-console.vercel.app/chat", keepOpen: true})`.
3. Use `snapshot` + `fill` on the chat textarea (test id historically `copilot-chat-textarea` in this app) and submit; `wait_for` / repeated `snapshot` to observe states.  
4. Record network with `tools.browse.network` if you need to cite endpoints in notes (optional).  
**Caveat:** Browse MCP drives a real browser session; Clerk login may require manual handoff (`handoff`) if 2FA/session issues occur. Do **not** automate captcha/login bypass.

### C. Backend sanity (optional, for your confidence)

- Gateway health (example): `GET https://gateway-795m.onrender.com/health` (per deployment docs patterns) — expect 200 if up (cold starts possible on free tier).
- If you run locally, follow `README.md` / `make dev` and `docs/deployment-guide.md`; ensure `NEBIUS_API_KEY` set for live LLM/retrieval paths, or expect `retrieval_unavailable` style failures.

### D. What to do if the live flow fails

- **Retrieval unavailable / errors:** mention “marketplace search temporarily unavailable” is a possible demo condition; switch to a **pre-recorded fallback** of the same query results.
- **Stall at mediation:** cut to fallback award/settlement clip; VO: “In this demo we show the completed approval and settlement path from a verified run.”
- **PayPal not configured:** show UI states only up to funding approval and explain Sandbox requires configured credentials; do not fabricate a successful charge.

---

## Quick reference: exact phrases to use (VO-safe)

- “MarketMesh is the agent-to-agent exchange; Verifund is the trust and settlement layer.”
- “The assistant searches the marketplace with your constraints—under fifteen hundred dollars for a programming laptop—and presents comparable options.”
- “Before sourcing, I confirm the mandate: quantity, budget ceiling, warranty and return expectations, and must-haves.”
- “Seller agents negotiate over A2A; the Buyer agent aggregates offers.”
- “Ranking and eligibility checks are computed by code, not chosen by the language model.”
- “A human must approve before any order is placed.”
- “In PayPal Sandbox mode, no live funds are used.”
- “Evidence is verified against agreed requirements before release is approved.”

---

## Appendix: key file map (for reviewers/editors)

- Console chat: `apps/console/features/chat/chat.tsx`, `product-cards.tsx`, `product-recommendations.tsx`, `sourcing-mandate-card.tsx`, `verifund-tools.tsx`
- Console CopilotKit route: `apps/console/app/api/copilotkit/[[...slug]]/route.ts`
- Orchestrator: `apps/orchestrator_agent/orchestrator_agent/server.py`, `agent.py`, `marketplace.py`, `mediation.py`
- Buyer graph/API: `apps/buyer_agent/buyer_agent/graph.py`, `server.py`, `console_api.py`, `settlement_api.py`
- Verifund: `apps/verifund_agent/verifund_agent/*`, `apps/verifund_control_plane/verifund_control_plane/*` (domain, paypal, webhooks, checkout)
- Deploy/config: `render.yaml`, `.env.example`, `docs/deployment-guide.md`, `docs/sponsor-integrations.md`, `docs/project-story.md`, `docs/workflow.md`