# Verifund PayPal Sandbox guide

Verifund is the optional settlement subsystem for MarketMesh. This guide wires it
to PayPal Sandbox. `VERIFUND_MODE=off` remains the default and requires none of
this configuration.

Verifund v1 is Sandbox only. The control plane rejects
`https://api-m.paypal.com`, refuses default development secrets, and exits when the
sandbox configuration is incomplete. Do not point it at a live PayPal app.

## 1. What you need

| Item | Purpose |
| --- | --- |
| PayPal Developer account | Sandbox accounts, REST app, webhooks |
| Platform Business account | Owns the REST app, captures funds, sends Payouts |
| Buyer Personal account | Approves the checkout |
| One Personal account per seller | Receives Payouts; four recommended |
| Public HTTPS tunnel | Delivers PayPal return/cancel redirects and webhooks |
| Python + Node.js toolchain | `make setup`, `make dev` |

## 2. Create the sandbox accounts

1. Open <https://developer.paypal.com/dashboard/accounts>.
2. Create or confirm a **Business** sandbox account for the platform, country
   `US`, currency `USD`.
3. Create a **Personal** sandbox account for the buyer.
4. Create four **Personal** sandbox accounts for sellers. Confirm each email and
   confirm that it can receive Payouts.
5. Add sandbox funds to the platform Business account. Payouts fail without a
   balance.

Record every email. Seller payout emails must be unique and must not reuse the
platform or buyer account.

## 3. Create the REST app and webhook

1. In the Developer Dashboard, open **Apps & Credentials** in the **Sandbox**
   tab.
2. Create an app under the platform Business account.
3. Copy the **Client ID** and **Secret** into `PAYPAL_CLIENT_ID` and
   `PAYPAL_CLIENT_SECRET`.
4. Add a webhook with URL `https://<public-host>/webhooks/paypal`.
5. Subscribe to these events:
   - `PAYMENT.CAPTURE.COMPLETED`
   - `PAYMENT.CAPTURE.PENDING`
   - `PAYMENT.CAPTURE.DECLINED`
   - `PAYMENT.CAPTURE.REFUNDED`
   - `PAYMENT.CAPTURE.REVERSED`
   - `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`
   - `PAYMENT.PAYOUTS-ITEM.FAILED`
   - `PAYMENT.PAYOUTS-ITEM.BLOCKED`
   - `PAYMENT.PAYOUTS-ITEM.DENIED`
   - `PAYMENT.PAYOUTS-ITEM.RETURNED`
   - `PAYMENT.PAYOUTS-ITEM.REFUNDED`
   - `PAYMENT.PAYOUTS-ITEM.REVERSED`
   - `PAYMENT.PAYOUTS-ITEM.ONHOLD`
   - `PAYMENT.PAYOUTS-ITEM.UNCLAIMED`
   - `PAYMENT.PAYOUTS-ITEM.CANCELED`
6. Copy the webhook ID into `PAYPAL_WEBHOOK_ID`.
7. Copy the Business account email into `PAYPAL_PLATFORM_EMAIL` and the Personal
   buyer email into `PAYPAL_BUYER_EMAIL`.

The webhook must belong to the same REST app as the client credentials. Preflight
verifies this with `GET /v1/notifications/webhooks/{id}`.

Do not subscribe the release flow to `CHECKOUT.ORDER.COMPLETED`; PayPal documents
it as marketplace/platform-only.

## 4. Start the HTTPS tunnel

PayPal must reach the webhook and must redirect the buyer to the console. Start
the control plane first, then expose only port 9300:

```bash
cloudflared tunnel --url http://127.0.0.1:9300
```

Use the printed `https://...` origin as `VERIFUND_PUBLIC_BASE_URL`. Keep
`VERIFUND_CONSOLE_BASE_URL=http://127.0.0.1:3000`; the buyer's browser must be
able to open the local console after PayPal redirects back.

With ngrok:

```bash
ngrok http 9300
```

## 5. Configure `.env`

Generate each secret with `openssl rand -hex 32`. Do not reuse the development
defaults from `.env.example`.

```dotenv
VERIFUND_MODE=sandbox
VERIFUND_PORT=9300
VERIFUND_PUBLIC_BASE_URL=https://<public-host>
VERIFUND_CONSOLE_BASE_URL=http://127.0.0.1:3000
VERIFUND_ALLOW_PUBLIC_BIND=0

VERIFUND_OPS_TOKEN=<32+ random bytes>
VERIFUND_SELLER_TOKEN_SECRET=<32+ random bytes>
VERIFUND_LINK_SECRET=<32+ random bytes>
VERIFUND_RECEIPT_KEYS={"sandbox-1":"<32+ random bytes>"}
VERIFUND_RECEIPT_ACTIVE_KID=sandbox-1
BUYER_INTERNAL_TOKEN=<32+ random bytes>

VERIFUND_DATABASE_URL=sqlite+aiosqlite:///./data/verifund.db
VERIFUND_EVIDENCE_DIR=./data/evidence
VERIFUND_INSPECTION_WINDOW_HOURS=0
VERIFUND_RECONCILER_ENABLED=true
VERIFUND_SELLER_PAYOUT_EMAILS={"northwind-audio":"<seller-1>","circuitforge":"<seller-2>","aurora":"<seller-3>","summit-tech":"<seller-4>"}

PAYPAL_ENV=sandbox
PAYPAL_API_BASE=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=<client-id>
PAYPAL_CLIENT_SECRET=<client-secret>
PAYPAL_WEBHOOK_ID=<webhook-id>
PAYPAL_PLATFORM_EMAIL=<platform-business-email>
PAYPAL_BUYER_EMAIL=<buyer-personal-email>

# Optional: render the PayPal button inside the console chat.
VERIFUND_CHECKOUT_MODE=embedded
NEXT_PUBLIC_PAYPAL_CLIENT_ID=<same value as PAYPAL_CLIENT_ID>
NEXT_PUBLIC_PAYPAL_ENVIRONMENT=sandbox
```

`VERIFUND_CHECKOUT_MODE` defaults to `redirect`, which keeps the
PayPal-hosted checkout link. `embedded` renders the PayPal button in the chat
card; `NEXT_PUBLIC_PAYPAL_CLIENT_ID` must equal `PAYPAL_CLIENT_ID`, and
`PAYPAL_CLIENT_SECRET` stays server-side because Next.js creates and captures
the order. Fake mode always uses the redirect flow.

`VERIFUND_INSPECTION_WINDOW_HOURS=0` makes a one-shot demo release immediately
after verification. The production default is `24`; with a non-zero window the
transaction waits in `VERIFICATION_PENDING` until the deadline.

The buyer, seller, and orchestrator read their Verifund settings from the same
`.env`; `scripts/dev.py` copies the relevant values into each process.

## 6. Run the preflight

```bash
make verifund-preflight
```

Exit `0` means the sandbox configuration is complete. Exit `2` lists every failed
check. Add `--json` for machine-readable output.

| Check | What it proves |
| --- | --- |
| `mode` | `VERIFUND_MODE=sandbox` |
| `settings` | secrets are strong, the public URL is HTTPS, the receipt key exists, and the payout map is valid |
| `paypal_environment` | `PAYPAL_ENV=sandbox` and the sandbox API host |
| `paypal_accounts` | platform and buyer emails are set |
| `seller_payouts` | payout emails are present, unique, and not platform/buyer accounts |
| `reconciler` | webhook fallback and deadline processing are enabled |
| `paypal_oauth` | the client ID/secret obtain a sandbox access token |
| `paypal_webhook` | the webhook ID resolves for this REST app |
| `checkout_client_id` | embedded mode only: `NEXT_PUBLIC_PAYPAL_CLIENT_ID` equals `PAYPAL_CLIENT_ID` |
| `checkout_client_secret` | embedded mode only: `PAYPAL_CLIENT_SECRET` is set |
| `public_health` | the tunnel reaches `GET /health` |
| `public_webhook` | an unsigned `POST /webhooks/paypal` returns `401`, proving traffic reaches the control plane |

## 7. Exercise fake mode first

```bash
make verifund-smoke
make verifund-e2e
```

The first command runs the complete lifecycle against a temporary fake control
plane. The second starts the fake control plane, registry, buyer, Verifund A2A
agent, orchestrator, seller, and console; Playwright drives agreement/funding
and payout-release HITL decisions through chat, then checks the synchronized
Transaction Room. Fix fake-mode failures before spending time on PayPal.

## 8. Run the sandbox smoke

```bash
make down
VERIFUND_SANDBOX_SMOKE=1 make verifund-sandbox-smoke
```

The script is manual and never runs in CI. It:

1. Creates an award, agreement, acceptance, and approval.
2. Creates the PayPal Sandbox order and prints the payer-action URL.
3. Waits for you to pay with the buyer Personal account.
4. Reports the purchase order and uploads shipment/delivery evidence.
5. Verifies policy and performs the audited release.
6. Waits for the Payouts batch and fetches the signed receipt.

Record the printed transaction ID, agreement hash, capture ID, payout batch/item
IDs, and receipt hash as the sandbox evidence required by the design.

If the inspection window is not zero, the script exits `3` after verification and
prints the deadline. That is not a failure: wait for the window, then release in
the console or rerun with `VERIFUND_INSPECTION_WINDOW_HOURS=0`.

## 9. Run the manual console flow

1. `make down`
2. `uv run python scripts/dev.py --verifund sandbox`
3. Open <http://127.0.0.1:3000>, run the sample brief, and review the exact
   agreement in the chat HITL card.
4. Approve agreement/funding in chat, then either pay with the embedded PayPal
   button or follow the checkout link, depending on `VERIFUND_CHECKOUT_MODE`.
5. Return to the run chat and wait for confirmed capture, seller order, two
   evidence items, and the control plane's verification result.
6. Review the evidence summary and approve payout release in the separate chat
   HITL card; the verified receipt appears in chat.
7. Open the Transaction Room to inspect the synchronized timeline, evidence,
   payout state, and receipt.

The buyer keeps polling `GET /transactions/{id}/state`; chat and the
Transaction Room render the same run projection when `last_seq` advances.

### Embedded checkout (optional)

With `VERIFUND_CHECKOUT_MODE=embedded` the funding-approval decision is recorded
without creating a PayPal order. The chat card then:

1. Calls `POST /transactions/{id}/funding/prepare`, which validates the
   agreement binding and pins the funding deadline but leaves the transaction
   `AGREED`.
2. Creates the order with `@paypal/paypal-server-sdk` using `PAYPAL_CLIENT_ID`
   and `PAYPAL_CLIENT_SECRET`, then attaches it with
   `POST /transactions/{id}/funding/attach-order`, which moves the transaction to
   `FUNDING_PENDING`.
3. Captures through the SDK and calls `POST /transactions/{id}/funding/refresh`
   so the control plane stays the settlement authority. A capture that PayPal
   reports as `PENDING` polls `funding/refresh` until `FUNDED`.

Behavior notes:

- Closing the PayPal popup does not cancel the deal. The transaction stays
  `FUNDING_PENDING` until the funding deadline, and the buyer can retry; a retry
  creates a new order attempt after the previous order expires or the deadline
  passes.
- An explicit cancel in the card ends the run and cancels the transaction.
- If the PayPal SDK fails to load, the card offers **Pay on PayPal's site**,
  which falls back to the hosted checkout for the same transaction.

## 10. Webhook behavior

- `PAYMENT.CAPTURE.COMPLETED` records the capture and moves to `FUNDED`.
- `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` moves `PAYOUT_PENDING` to `RELEASED`.
- Capture or payout failures move to `REVIEW_REQUIRED`.
- Duplicate `event_id` values are stored once; the second delivery returns
  `{"status":"duplicate"}`.
- Unmatched or temporarily failed events stay in the webhook store; the
  in-process reconciler retries them and also polls PayPal when webhooks are lost.

## 11. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required` | Fill both in the sandbox app |
| `PAYPAL_WEBHOOK_ID is required` | Create the webhook and copy its ID |
| `VERIFUND_PUBLIC_BASE_URL must be HTTPS` | Start the tunnel and use its HTTPS origin |
| `webhook signature is invalid` | The webhook belongs to another app, or a proxy modified the body |
| `VERSION_ALREADY_USED` during funding | Wait for the reconciler, then `POST /transactions/{id}/funding/refresh` |
| Still `FUNDING_PENDING` | The buyer did not approve the PayPal order |
| `VERIFICATION_PENDING` after evidence | The inspection window is still open |
| `PAYOUT_PENDING` for a long time | The platform Business account has no sandbox balance |
| Payout item `RECEIVER_UNREGISTERED` | The seller email is unconfirmed or cannot receive Payouts |
| `REVIEW_REQUIRED` with `ledger_incomplete` or `funding_mismatch` | Resolve in PayPal; these reasons cannot be overridden in Verifund |
| `REVIEW_REQUIRED` after release | A refund or reversal arrived; reconcile it in PayPal |

## 12. Shut down and reset

```bash
make down
make reset   # removes data/verifund.db, data/evidence/, and the other local DBs
```

Never delete `data/verifund.db` while the control plane is running.
