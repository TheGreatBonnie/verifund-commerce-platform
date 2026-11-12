# Seller Evidence for a Laptop Sale — Under Simulated Order Fulfillment

The complete picture: **what evidence unlocks the money, and how you generate/test every piece of it without a real laptop or a real shipment.** The guiding principle is that the evidence chain must be _unbroken_ — listing → packing → delivery → (possible dispute) — and your simulation environment must let you prove that chain holds, and break it on demand, in minutes instead of days.

---

## 1. The Evidence Chain, Stage by Stage

### Stage 1 — Deal Creation (the Baseline)

Recorded _before_ funds are held; everything later is compared against this.

| Evidence item                                                                                         | Why it matters                                                                     | How you simulate/test it                                                                                                                                                                                 |
| ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Serial number** recorded in the deal                                                                | The atomic unit of proof — kills swap/empty-box scams                              | Fixture: a pool of fake serials (`SN-SANDBOX-001...`). Assert the machine _refuses to activate_ the deal (`DEAL_ACTIVATED` guard) if the serial field is missing.                                        |
| **Timestamped condition photos** (4 sides, screen, keyboard, ports, disclosed defects)                | Defines "as described" — the dispute comparator measures buyer claims against this | Seed with real photos of any laptop. Hash them into the deal record. Test: run the photo-comparator plugin against (a) identical photos → PASS, (b) photos with visible new damage → FAIL with findings. |
| **Provenance-code photo** — agent shows a one-time code; seller photographs it on the laptop's screen | Proves photos are of _this_ deal, not stock images                                 | Scenario key `provenance_ok`. The fake camera/upload step stamps the deal code onto the image; the vision verifier checks code↔deal match.                                                               |
| **Spec screenshot** (About This Mac / System Info) + OEM warranty-API match                           | Verifies "16GB/512GB" claims                                                       | Fixture: mock OEM API returns specs per serial. Scenario `specs_mismatch` → verifier FAIL at Stage 1, deal never activates.                                                                              |
| **Structured condition declaration** (battery cycles, locks/MDM status, accessories)                  | Ambiguity defaults against the seller in disputes                                  | Schema-validated form in your UI; a missing field blocks activation.                                                                                                                                     |

### Stage 2 — Shipment (SUBMITTED trigger)

| Evidence item                                       | Why it matters                                                    | How you simulate/test it                                                                                                                                          |
| --------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Carrier tracking number**                         | Primary verification input for `TRACKING_CONFIRMATION`            | Fake carrier API (Postman Mock Server fits — sponsor synergy). Format: `SANDBOX-<scenario>`. Your production poller hits it unmodified.                           |
| **Unit + box + label in one photo**, serial visible | Ties the specific laptop to the specific shipment                 | Upload step in the seller UI; verifier checks serial in image ↔ deal record. Scenario `packing_photo_missing` → stall at VERIFYING, auto-fail after grace period. |
| **Sealed-box photo with label**                     | Continuity evidence                                               | Same upload flow; stored hash-chained in the audit log.                                                                                                           |
| **Insurance at declared value**                     | Shifts carrier-loss liability; seller's on-record value statement | Field in the submission form; assert capture is _blocked_ above $500 if insurance is absent (your policy-as-code).                                                |
| **Carrier pickup weight**                           | Refutes "empty box" claims                                        | Mock carrier returns pickup weight with first tracking event. Scenario `weight_anomaly` (2kg deal, 0.3kg pickup) → verifier flags, optional HUMAN_REVIEW.         |

### Stage 3 — Delivery (auto-verification)

No seller action — the machine polls the (fake) carrier until `delivered`:

- **Happy path:** `SANDBOX-happy` script resolves `in_transit → out_for_delivery → delivered` over N polls → `VERDICT_PASS` → capture → **inspection window** (compressed to minutes) → no claim → CAPTURED.
- **Signature required:** above threshold, verifier requires `delivered_signed` event; plain `delivered` → `NEEDS_HUMAN`.
- **Never arrives:** `SANDBOX-never_delivers` stays `in_transit` until the (compressed) deadline → `DELIVERY_TIMEOUT` → **VOIDED — assert via PayPal sandbox transactions API that the buyer was never charged.**

### Stage 4 — Dispute (if a claim opens within the window)

This is where the evidence chain earns its keep. Simulate each claim type with buyer photo fixtures:

| Simulated buyer claim                           | Buyer evidence fixture                 | Seller chain state                                                          | Mediator verdict                                          | PayPal-side truth to assert                                   |
| ----------------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------- |
| "Empty box"                                     | Photo of empty box                     | Pickup weight 2.1kg, packing photos, insurance, signature                   | **Seller wins** → CAPTURED                                | Capture stands; seller sandbox balance +$700                  |
| "Different laptop inside"                       | Photo of unit with _other_ serial      | Serial on record matches listing/packing photos                             | **Seller wins** → CAPTURED                                | Capture stands                                                |
| "More scratched than described"                 | Photos showing new damage vs. baseline | Stage-1 photos disclosed existing scratches; comparator isolates new damage | **Buyer wins** → VOIDED (pre-capture)                     | Authorization voided; zero captures on the order              |
| "Won't power on"                                | Video of dead unit                     | Stage-1 boot photo + serial shot                                            | **Seller wins** (condition at shipment proven) → CAPTURED | Capture stands                                                |
| "Partial agreement" (small scratch, works fine) | —                                      | —                                                                           | `MEDIATION_PARTIAL` 80/20 → PARTIALLY_CAPTURED            | Capture + partial refund via refunds API; assert both amounts |

---

## 2. Wiring It Together: The `verification_config` for Electronics

```json
{
  "category": "electronics",
  "verification_method": "TRACKING_CONFIRMATION",
  "mode": "sandbox",
  "scenario": "happy_path",
  "requires": {
    "serial_at_deal_creation": true,
    "provenance_photo": true,
    "packing_photo_serial_visible": true,
    "insurance_min_value": 500,
    "signature_required": true
  },
  "inspection_window_hours": 2,
  "auto_release_hours": 1,
  "revision_rounds": 0,
  "carrier": {
    "base_url": "https://mock-carrier.example",
    "tracking_format": "SANDBOX-{scenario}"
  }
}
```

Two switches do the heavy lifting for testing: `mode: "sandbox"` routes plugins to fixtures, and compressed windows (`inspection_window_hours: 2`) make the whole lifecycle run in minutes.

---

## 3. The Simulated Fulfillment Pipeline (What Actually Executes)

```
Seller submits (UI):
  tracking_no = "SANDBOX-dispute_seller_wins"
  packing_photos = [unit+box+label, serial close-up, sealed box]
  insurance_value = 700
        │
        ▼
State machine: SUBMITTED → VERIFYING
        │
        ▼
Fake carrier (Postman mock, scripted):
  poll 1: in_transit (pickup weight 2.1kg)
  poll 2: delivered_signed (pod: "J. DOE")
        │
        ▼
Verifier:
  tracking ✅  signature ✅  weight plausible ✅
  packing photos: serial == deal record ✅
        │
        ▼
VERDICT_PASS → CAPTURED (capture request → webhook confirms)
        │
        ▼
[time compressed] buyer opens claim "empty box"
  + buyer fixture: photo of empty box
        │
        ▼
DISPUTED → AI mediator:
  pickup weight 2.1kg  vs.  buyer's "empty" claim
  packing photo chain intact
  → verdict: SELLER_WINS
        │
        ▼
CAPTURED (final) — dispute resolved in seller's favor via PayPal disputes API
```

Assert at the end, via PayPal sandbox API: exactly one capture for $700, no void, no refund. Machine state and PayPal truth agree — that's the definition of "tested."

---

## 4. Minimum Scenario Set (Given Today's Deadline)

Submission closes **today, 2pm PT**. If time is short, these four scenarios prove the entire thesis:

1. **`happy_path`** — full chain → CAPTURED (money moves only after verified delivery)
2. **`never_delivers`** — timeout → VOIDED (buyer never charged)
3. **`dispute_seller_wins`** — claim → evidence chain prevails → CAPTURED
4. **`dispute_buyer_wins`** — claim → broken/undisclosed condition → VOIDED or partial refund

Pre-seed the demo database with these four completed runs, keep one live sandbox checkout on video, and expose the `/scenarios` replay page so judges can click and watch.

---

## 5. One Sentence Summary

**The seller earns release by an unbroken, machine-checkable chain — serial, provenance, packing, weight, signature — and you prove the system works by scripting every link of that chain in a sandbox where packages are fixtures, days are minutes, and PayPal's sandbox ledger is the final arbiter of truth.**

Want the runnable scenario-runner code for these four scenarios, or the checklist version of this evidence spec to paste into your README?
