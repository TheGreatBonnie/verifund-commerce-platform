# Verifund: Seller Evidence Requirements for Laptop Fulfillment and Payment Release

## 1. Purpose and scope

This document explains the evidence a seller should provide when selling
a laptop through Verifund, how Verifund can verify that evidence, and
how the evidence contributes to the decision to release the seller's
payment.

It also describes a simulated order-fulfillment implementation for
demonstrating the complete workflow without depending on a live shipping
carrier or real-world laptop transaction.

The central principle is:

> Evidence submission, evidence verification, and authorization to
> release payment are three different things.

A seller may upload every requested file and still have outstanding
verification failures. Likewise, a successful delivery event does not,
by itself, prove that the correct laptop was delivered in the agreed
condition.

The evidence chain should establish:

`Product listing → Product identity → Product condition → Packaging → Shipment → Delivery → Buyer inspection → Payment release`

The exact requirements should be generated from the transaction
agreement, product category, transaction value, and shipping method. A
high-value laptop should generally have stronger identity, shipping, and
delivery evidence than a low-value accessory.

------------------------------------------------------------------------

## 2. What Verifund needs to establish

Before authorizing a seller payout, Verifund should be able to answer
these questions:

1.  **What was sold?** The laptop's make, model, configuration, and
    unique serial number must be recorded.
2.  **What condition was promised?** The seller's description and
    declared defects must be recorded before shipment.
3.  **Does the laptop match the agreement?** Its specifications and
    relevant functional checks must match the agreed requirements.
4.  **Was the same laptop packaged?** The product identity should be
    connected to the packaging evidence.
5.  **Was the package actually handed to a carrier?** A shipping label
    alone is not proof of carrier acceptance.
6.  **Was the package delivered?** Delivery should be supported by
    carrier tracking and, where required, proof of delivery.
7.  **Did the buyer receive what was agreed?** The buyer should have an
    opportunity to inspect the laptop and accept it or raise a supported
    claim.
8.  **Can the payment be released?** The transaction must satisfy the
    agreement and Verifund's release policy, with no unresolved dispute
    or other blocking condition.

### 2.1 Evidence statuses

Use explicit statuses rather than treating an uploaded file as
automatically approved.

  -----------------------------------------------------------------------
  Status                              Meaning
  ----------------------------------- -----------------------------------
  `NOT_SUBMITTED`                     The seller has not supplied the
                                      required evidence.

  `SUBMITTED`                         Evidence has been uploaded but has
                                      not yet been checked.

  `PROCESSING`                        Automated or manual verification is
                                      in progress.

  `VERIFIED`                          The evidence passed the applicable
                                      checks.

  `REJECTED`                          The evidence failed a check or is
                                      unusable.

  `NEEDS_REVIEW`                      Automated checks were inconclusive
                                      and a human decision is required.

  `WAIVED`                            An authorized policy decision
                                      waived a requirement, with a
                                      recorded reason.
  -----------------------------------------------------------------------

A requirement should not be considered complete merely because a file
exists. The verification result and any findings should be stored
separately from the submission.

------------------------------------------------------------------------

## 3. Stage One: Establish the laptop's identity and condition

This stage takes place when the seller creates or accepts the
transaction and before the laptop is packaged.

### 3.1 Laptop serial number

**Seller should provide:** - The laptop's full serial number. - The
manufacturer and model. - A clear photograph of the physical
serial-number label, where the device has one. - A record of the serial
number displayed in the laptop's system information, if available.

**Why it matters**

The serial number is the primary identity reference connecting the
original listing, seller evidence, packaging evidence, and buyer
inspection. If the buyer later reports receiving a different laptop,
Verifund can compare the buyer's serial-number evidence with the
seller's original record.

**Verification** 1. Extract the serial number from the submitted
photograph using OCR. 2. Compare the extracted value with the serial
number entered by the seller. 3. Compare it with the system-information
record, where available. 4. Check manufacturer or warranty information
where an appropriate lookup service is available. 5. Flag unreadable,
inconsistent, duplicated, or suspicious values for review.

**Release implication**

A missing or mismatched serial number should normally block activation
of the fulfillment task or progression to shipment verification. A human
reviewer may resolve an OCR failure, but should not silently accept
conflicting device identities.

### 3.2 Multi-angle product-condition photographs

**Seller should provide clear photographs of:** - Front of the laptop
with the screen visible. - Back or top cover. - Left side and ports. -
Right side and ports. - Keyboard and trackpad. - Underside of the
laptop. - Serial-number label. - Screen while powered on, where
practical.

The seller should disclose visible defects, including scratches, dents,
cracks, missing keys, screen marks, damaged ports, and other faults.

**Why it matters**

These photographs establish the laptop's pre-shipment visual condition.
They provide a baseline against which the buyer's inspection photographs
can be compared.

**Verification** - Check that all required views are present and
sufficiently clear. - Check for consistency between photographs and the
declared laptop model. - Use image analysis to identify visible damage
or inconsistencies. - Store each original file, submission timestamp,
transaction ID, seller ID, and cryptographic hash. - Compare
buyer-submitted images with the seller's baseline images if a condition
dispute is raised.

**Limitations**

A photograph does not prove that the laptop was photographed live, that
it was not manipulated, or that it represents the device eventually
placed in the package. A trusted capture flow, short-lived capture
challenges, provenance checks, and continuity evidence can increase
confidence, but no single photograph should be treated as conclusive
proof.

### 3.3 Transaction-specific provenance photograph

**Seller should provide:** - A photograph of the laptop displaying a
unique, one-time Verifund code. - The code should be generated for the
specific transaction and expire after a short period.

Example code:

`VF2048-839251`

The seller displays the code on the laptop screen and captures the
laptop with the code visible.

**Why it matters**

A transaction-specific challenge makes it harder to reuse an old listing
photograph or submit generic stock images as evidence for a particular
order.

**Verification** 1. Verifund generates a unique challenge code. 2. The
seller submits the requested photograph. 3. OCR extracts the visible
code. 4. The system compares it with the active challenge for that
transaction. 5. The system checks the challenge expiry and whether it
has already been used. 6. The image is stored with its hash and
submission metadata.

**Limitations**

A challenge-code photograph reduces reuse risk but does not prove
genuine live capture or eliminate image manipulation. Stronger assurance
may require an in-app capture flow, short-lived challenges,
image-integrity checks, and human review of suspicious submissions.

### 3.4 Hardware specifications

The seller should provide the actual configuration and supporting
diagnostic evidence.

  -----------------------------------------------------------------------
  Specification                       Example evidence
  ----------------------------------- -----------------------------------
  Manufacturer and model              System information or device
                                      details

  Processor (CPU)                     System information or diagnostic
                                      report

  Memory (RAM)                        System information or diagnostic
                                      report

  Storage capacity and type           Disk/system report

  Graphics processor (GPU)            System information or diagnostic
                                      report

  Operating system                    System information and activation
                                      status

  Battery health and cycle count      Battery report or manufacturer
                                      diagnostic

  Display and other agreed features   Relevant diagnostics or inspection
                                      evidence
  -----------------------------------------------------------------------

**Why it matters**

A laptop can look correct while having a different processor, less
memory, smaller storage, a degraded battery, or a different GPU than the
listing promised.

**Verification** - Compare each submitted value with the transaction
agreement. - Validate that required fields are present and use expected
formats. - Where possible, inspect a structured diagnostic report rather
than relying only on screenshots. - Flag material mismatches for seller
correction or human review.

Screenshots can be edited. A diagnostic report is stronger when it is
generated through a trusted process and protected against alteration.
Verifund should record the evidence source and confidence level instead
of describing every screenshot as independently verified hardware truth.

### 3.5 Condition and functionality declaration

The seller should complete a structured declaration covering:

-   Overall cosmetic condition and known defects.
-   Battery health and cycle count, where available.
-   Whether the laptop powers on and boots.
-   Screen, keyboard, trackpad, webcam, speakers, microphone, Wi-Fi,
    Bluetooth, and ports.
-   Charger and other included accessories.
-   BIOS or firmware password status.
-   Mobile Device Management (MDM) enrollment or organizational
    management.
-   Activation Lock or equivalent device lock status, where relevant.
-   Operating-system activation status.
-   Previous repairs or replacement parts.
-   Warranty status and any remaining coverage.
-   Any other condition specifically promised in the listing.

**Why it matters**

Some restrictions are not visible in photographs. A laptop can be
cosmetically excellent but unusable because it is BIOS-locked,
MDM-managed, activation-locked, or missing an agreed operating-system
license.

**Verification** - Validate that all mandatory declaration fields are
completed. - Compare declared values with the listing and transaction
agreement. - Require supporting evidence for fields that materially
affect value or usability. - Route conflicting or high-risk declarations
to review.

The seller's declaration is an assertion, not independent proof.
Verifund should label it accordingly and use available diagnostic or
buyer-inspection evidence to corroborate it.

------------------------------------------------------------------------

## 4. Stage Two: Prove that the laptop was packaged

The objective is to connect the identified laptop to the package that
will be shipped.

### 4.1 Laptop inside the package

**Seller should provide:** - A photograph showing the laptop immediately
before the package is sealed. - The laptop's serial number visible in
the image if practical. - A photograph showing relevant protective
materials and included accessories.

**Why it matters**

This creates a visual record that the laptop was placed in the package
and helps connect the product identity to the shipment.

**Verification** - Check that the image is clear and belongs to the
transaction's evidence set. - Compare visible product details with the
original product photographs. - Compare the serial number where it is
visible. - Record the upload time, file hash, and evidence metadata.

A photograph of a laptop beside an open box is weaker than a photograph
clearly showing the laptop inside the box. Neither proves by itself that
the same contents remained in the package after the photograph was
taken.

### 4.2 Sealed-package photograph

**Seller should provide:** - A photograph of the closed and sealed
package. - A photograph showing the shipping label, if the label is
already attached. - A clear view of any tamper-evident seal, where used.

**Why it matters**

The sealed-package photograph records the package's appearance at the
point the seller says it was ready for dispatch.

**Verification** - Check that the label corresponds to the transaction's
shipment record. - Record the image hash and timestamp. - Compare
package identifiers and label details with the shipping information.

A sealed-box photograph is not proof that a carrier accepted the
package. Verifund must still obtain carrier pickup or acceptance
evidence.

### 4.3 Packaging and shipment metadata

Record: - Transaction ID. - Seller ID. - Package identifier, if used. -
Carrier name. - Tracking number. - Shipping service. - Shipment date. -
Destination confirmation appropriate to the privacy policy. - Declared
package weight, if available. - Expected delivery date.

The tracking number must be associated with the correct transaction. A
seller-entered tracking number should not be treated as
carrier-confirmed until it has been checked against a carrier source or
an explicitly simulated carrier service.

### 4.4 Shipping insurance

For higher-value laptops, Verifund may require shipping insurance
according to its risk policy.

Distinguish these states: - Seller says the shipment is insured. -
Insurance was purchased. - The carrier or insurer confirms the
coverage. - A claim has actually been filed or paid.

These are not equivalent. Store the coverage amount, policy reference,
covered risks, and any exclusions when available.

A fixed threshold such as requiring insurance above a particular
transaction value can be used in a demo policy, but the threshold should
be configurable by product category, value, shipping method, and
Verifund policy.

### 4.5 Carrier pickup weight

If the carrier supplies an acceptance weight, store it.

**Why it matters**

A package weight can help identify anomalies. For example, a package
recorded as substantially lighter than expected may warrant
investigation.

**Verification** - Compare carrier-reported weight with the expected
package weight. - Apply a configurable tolerance. - Flag significant
differences for review.

Weight is supporting evidence only. It does not prove that the correct
laptop was inside the box.

------------------------------------------------------------------------

## 5. Stage Three: Verify shipment and delivery

### 5.1 Carrier tracking events

Verifund should track a shipment through events such as:

  -----------------------------------------------------------------------
  Event                               Meaning
  ----------------------------------- -----------------------------------
  `LABEL_CREATED`                     A label exists; the carrier may not
                                      have the package yet.

  `PICKED_UP`                         The carrier has accepted or
                                      collected the package.

  `IN_TRANSIT`                        The package is moving through the
                                      carrier network.

  `OUT_FOR_DELIVERY`                  The package is on a delivery route.

  `DELIVERED_SIGNED`                  The carrier reports delivery with a
                                      signature or equivalent
                                      confirmation.

  `DELIVERY_EXCEPTION`                A delivery problem or exception has
                                      been reported.

  `RETURN_TO_SENDER`                  The package is being returned.
  -----------------------------------------------------------------------

The system should distinguish label creation from carrier acceptance. A
label-created event alone must not satisfy the shipment requirement.

### 5.2 Proof of delivery

For a laptop transaction, especially a high-value one, collect proof of
delivery where supported:

-   Delivery timestamp.
-   Carrier tracking number.
-   Delivery status.
-   Recipient name or reference, subject to privacy rules.
-   Signature or signature reference, where required.
-   Carrier proof-of-delivery document or event reference.
-   Delivery location information, where the carrier provides it.

**Why it matters**

Proof of delivery helps establish that the carrier reports the package
as delivered to the destination.

**Limitations**

A delivery scan or signature does not prove that the correct laptop was
inside the package or that it arrived in the promised condition. That is
why buyer inspection and product-identity checks remain important.

### 5.3 Delivery weight

If the carrier provides a delivery weight, compare it with the pickup
weight. A material difference can be used to trigger an investigation.

Do not make delivery weight mandatory if the carrier does not supply it.
Treat it as optional corroborating evidence.

------------------------------------------------------------------------

## 6. Stage Four: Buyer inspection and dispute handling

The Verifund transaction scenario uses a **48-hour buyer inspection
window**. The window should be represented in the transaction agreement
and applied consistently. The exact policy may vary by product, shipping
method, and transaction terms.

During inspection, the buyer should be able to:

-   Accept the laptop.
-   Report a mismatch or defect.
-   Submit photographs or video.
-   Submit relevant diagnostic results.
-   Open a dispute.
-   Request a partial settlement where the parties and policy permit it.

### 6.1 Buyer serial-number confirmation

The buyer should photograph the received laptop's serial number and
submit it to Verifund.

Verifund compares the buyer's serial number with the original
seller-submitted serial number.

A mismatch should suspend automatic payout and open an investigation. It
may indicate that the wrong device was sent, but the investigation
should also consider evidence-submission errors and other explanations.

### 6.2 Buyer condition photographs

The buyer should be able to submit photographs of: - Front and screen. -
Back or top cover. - Sides and ports. - Keyboard and trackpad. -
Underside and serial label. - Any alleged damage or missing component.

Compare these images with the seller's pre-shipment baseline. The
comparison can help identify damage that may have existed before
shipment or appeared during transit.

Image comparison should support, not replace, human review when the
evidence is ambiguous.

### 6.3 Buyer functionality checks

For a laptop, useful inspection checks include:

-   Power-on and successful boot.
-   BIOS or firmware access where appropriate.
-   Operating-system startup.
-   CPU, RAM, storage, and GPU information.
-   Battery health and charging.
-   Screen and display output.
-   Keyboard and trackpad.
-   Wi-Fi and Bluetooth.
-   Webcam, microphone, and speakers.
-   Ports and charger.
-   BIOS password, MDM, or activation restrictions.

The buyer may submit screenshots, reports, or a short video
demonstrating relevant checks. The evidence required should be
proportionate to the claims in the listing and the transaction's risk.

### 6.4 Dispute examples

#### Scenario A: Buyer reports an empty box

Relevant evidence: - Seller's product and serial-number records. -
Photograph of the laptop inside the package. - Sealed-package
photograph. - Carrier pickup record and weight. - Delivery record and
any delivery weight. - Buyer photographs or video of the received
package and contents.

The system should not automatically decide for either party based on one
image or one weight value. It should assemble the evidence timeline and
route the case for review under the dispute policy.

#### Scenario B: Buyer receives a different laptop

Relevant evidence: - Seller's original serial number and label
photograph. - System-information evidence. - Packaging photographs. -
Buyer serial-number photograph.

A verified serial mismatch is a strong reason to suspend automatic
payout and investigate possible substitution or evidence error.

#### Scenario C: Buyer reports undisclosed scratches

Relevant evidence: - Seller's original multi-angle condition
photographs. - Seller's condition declaration. - Buyer photographs
showing the alleged scratches. - Submission timestamps and image
metadata.

If the damage is credibly shown to have existed before shipment and was
not disclosed, the buyer may have a valid claim under the agreement.

#### Scenario D: Laptop does not power on

Relevant evidence: - Seller's pre-shipment boot or diagnostic
evidence. - Seller's declaration. - Packaging and shipping records. -
Buyer video showing the failed power-on attempt. - Charger and
power-related checks.

The investigation should consider whether the laptop was already
defective, was damaged in transit, or whether the buyer's test was
incomplete.

#### Scenario E: Partial settlement

If the parties agree and the applicable policy permits it, Verifund can
record a partial settlement. The agreed allocation, reason, approvals,
and remaining balance must be auditable. The system should not invent a
partial settlement amount or release it without the required
authorization.

------------------------------------------------------------------------

## 7. Simulated order fulfillment for Verifund

A simulated fulfillment environment allows Verifund to demonstrate the
seller workflow, evidence checks, tracking events, inspection, dispute
handling, and payout authorization without a live carrier integration.

The simulation should behave like a real workflow from the user's
perspective while clearly identifying all generated evidence and carrier
events as **simulated**.

### 7.1 Suggested fixture structure

``` text
fixtures/
└── laptop/
    ├── product/
    │   ├── front.jpg
    │   ├── back.jpg
    │   ├── left-side.jpg
    │   ├── right-side.jpg
    │   ├── keyboard.jpg
    │   ├── screen.jpg
    │   └── serial-number.jpg
    ├── provenance/
    │   └── provenance-code.jpg
    ├── specifications/
    │   ├── system-info.png
    │   ├── hardware-report.json
    │   └── battery-report.json
    ├── packaging/
    │   ├── laptop-box-label.jpg
    │   ├── laptop-inside-box.jpg
    │   └── sealed-box.jpg
    ├── delivery/
    │   ├── proof-of-delivery.json
    │   └── delivery-signature.png
    └── disputes/
        ├── empty-box.jpg
        ├── different-serial.jpg
        ├── damaged-laptop.jpg
        └── dead-laptop.mp4
```

Use genuine sample laptop photographs where licensing and usage rights
permit. Use clearly fictional serial numbers, transaction identifiers,
diagnostic records, and carrier events. Do not present fabricated
evidence as genuine proof of a real transaction.

A transaction-specific challenge code can be composited onto a fixture
image to demonstrate the provenance-code workflow. The UI and stored
record must label that image as simulated; it must not be represented as
a genuine live capture.

### 7.2 Mock carrier API

Create a small mock carrier service using FastAPI or another backend
already used by the project.

Example endpoint:

``` http
GET /tracking/SANDBOX-HAPPY
```

Example simulated response:

``` json
{
  "tracking_number": "SANDBOX-HAPPY",
  "carrier": "Verifund Sandbox Carrier",
  "simulation": true,
  "events": [
    {
      "status": "PICKED_UP",
      "timestamp": "2026-11-12T09:00:00Z",
      "weight_kg": 2.1
    },
    {
      "status": "IN_TRANSIT",
      "timestamp": "2026-11-12T14:00:00Z"
    },
    {
      "status": "OUT_FOR_DELIVERY",
      "timestamp": "2026-11-13T07:00:00Z"
    },
    {
      "status": "DELIVERED_SIGNED",
      "timestamp": "2026-11-13T11:30:00Z",
      "signature_reference": "SIM-SIGN-2048"
    }
  ]
}
```

The dates and event sequence above are illustrative fixture values. In a
working simulation, event times should be generated consistently with
the scenario clock or controlled test data.

### 7.3 Simulation scenarios

Implement several deterministic scenarios so reviewers can see how the
policy engine behaves.

  -------------------------------------------------------------------------
  Scenario                  Simulated behavior      Expected Verifund
                                                    behavior
  ------------------------- ----------------------- -----------------------
  `happy_path`              All seller evidence     Authorize payout after
                            passes; carrier accepts all release conditions
                            and delivers; buyer     are satisfied.
                            accepts.                

  `specs_mismatch`          Submitted RAM, CPU,     Block progression or
                            storage, or GPU differs payout; request
                            from the agreement.     correction or review.

  `packing_photo_missing`   Required package        Keep fulfillment
                            evidence is absent.     incomplete; notify
                                                    seller.

  `weight_anomaly`          Carrier-reported weight Flag shipment for
                            differs materially from review; do not treat
                            expected weight.        weight alone as proof
                                                    of fraud.

  `never_delivers`          Tracking remains in     Do not authorize
                            transit or ends in an   payout; apply the
                            exception.              agreement's timeout,
                                                    cancellation, or refund
                                                    process.

  `dispute_buyer_wins`      Buyer provides credible Resolve according to
                            evidence of a material  policy; prevent seller
                            mismatch or defect.     payout or apply the
                                                    agreed adjustment.

  `dispute_seller_wins`     Seller evidence and     Record the resolution
                            investigation support   and proceed only if all
                            the seller's position.  other release
                                                    conditions are met.
  -------------------------------------------------------------------------

Each scenario should be replayable and should produce an auditable event
history.

### 7.4 Example happy-path sequence

1.  Buyer and seller agree on the laptop, condition, specifications,
    price, shipping method, and inspection terms.
2.  Buyer completes payment through PayPal Sandbox.
3.  Verifund records the payment confirmation and the corresponding held
    amount in its internal transaction ledger.
4.  Seller submits serial-number evidence, product photographs,
    provenance evidence, hardware specifications, and condition
    declaration.
5.  Evidence services validate the submissions.
6.  Seller submits packaging photographs and shipping details.
7.  The mock carrier reports `PICKED_UP`.
8.  The mock carrier reports `IN_TRANSIT`, then `OUT_FOR_DELIVERY`.
9.  The mock carrier reports `DELIVERED_SIGNED`.
10. Verifund starts the buyer's 48-hour inspection window, as specified
    by the transaction scenario.
11. Buyer confirms the serial number and inspects the laptop.
12. Buyer accepts the laptop, or the inspection period expires under the
    agreed policy without an unresolved claim.
13. The policy engine confirms that every required condition is
    satisfied.
14. Verifund authorizes the seller payout.
15. The settlement coordinator initiates the configured PayPal payout
    and waits for provider confirmation.
16. Verifund records the provider reference and reconciles the
    settlement ledger.

The simulated carrier should not directly trigger payment release. It
should provide shipment facts to the fulfillment workflow. The policy
engine makes the release decision after considering all required
evidence and buyer-inspection outcomes.

------------------------------------------------------------------------

## 8. Payment and settlement architecture

### 8.1 Important distinction: payment capture versus seller payout

For the current Verifund design, the intended flow is:

1.  Buyer pays through PayPal Sandbox.
2.  Verifund receives the payment into its configured Sandbox merchant
    account.
3.  Verifund records the amount and transaction state in its internal
    ledger as funds held for the transaction.
4.  Seller fulfills the order.
5.  Verifund verifies the required evidence.
6.  Verifund evaluates the buyer-inspection outcome and any dispute.
7.  Verifund authorizes a separate seller payout.
8.  The payout provider confirms the transfer.
9.  Verifund reconciles the payout against its ledger.

Under this design, seller evidence authorizes **seller payout**. It does
not authorize the buyer's initial payment capture.

Do not mix this flow with a different authorization-and-capture model in
which delivery triggers capture of a previously authorized payment. The
two models have different payment states and operational requirements.

Also, do not describe the design as PayPal itself providing regulated
escrow unless that specific arrangement has been confirmed with the
payment provider and appropriate legal advisers. Holding, safeguarding,
and transferring customer funds can create legal, regulatory,
contractual, and provider-policy obligations. A hackathon simulation
should clearly distinguish its internal ledger model from a
production-approved funds flow.

### 8.2 Suggested transaction payment states

``` text
PAYMENT_CONFIRMED
        ↓
FUNDS_HELD_IN_LEDGER
        ↓
FULFILLMENT_SUBMITTED
        ↓
FULFILLMENT_VERIFIED
        ↓
INSPECTION_PENDING
        ↓
PAYOUT_AUTHORIZED
        ↓
PAYOUT_COMPLETED
```

Additional states may include:

-   `EVIDENCE_REJECTED`
-   `FULFILLMENT_BLOCKED`
-   `DELIVERY_EXCEPTION`
-   `DISPUTE_OPEN`
-   `PAYOUT_SUSPENDED`
-   `REFUND_PENDING`
-   `REFUND_COMPLETED`
-   `PARTIAL_SETTLEMENT_PENDING`
-   `PARTIAL_SETTLEMENT_COMPLETED`

A dispute should suspend automatic payout until the dispute is resolved.
A delivery timeout should trigger the cancellation, refund, or
investigation path defined by the agreement and policy.

### 8.3 Payout authorization conditions

The policy engine should authorize payout only when all applicable
conditions are satisfied:

1.  **Product identity verified:** the delivered device matches the
    agreed laptop identity, including the serial number where required.
2.  **Product compliance verified:** the specifications and declared
    condition meet the agreement, or an approved adjustment has been
    recorded.
3.  **Seller fulfillment verified:** required packaging, carrier
    acceptance, shipment, and delivery evidence has passed.
4.  **Buyer inspection resolved:** the buyer accepted the item, the
    inspection period expired under the agreement without a blocking
    claim, or a dispute was resolved.
5.  **No unresolved blocking issue:** there is no open dispute, policy
    violation, material evidence inconsistency, or payment restriction.
6.  **Settlement approved:** the payout amount and recipient are valid
    and the transaction is eligible under the applicable
    payment-provider arrangement.

A delivery event alone must never be sufficient to satisfy all these
conditions.

------------------------------------------------------------------------

## 9. Seller Fulfillment Workspace UI

The seller workspace should make it obvious which evidence is required,
which has been submitted, which has passed verification, and what is
preventing payout.

### 9.1 Suggested sections

1.  **Product identity**
    -   Serial number.
    -   Serial-number photograph.
    -   Manufacturer and model.
    -   Transaction-specific provenance photograph.
2.  **Product condition**
    -   Multi-angle photographs.
    -   Hardware specifications.
    -   Battery report.
    -   Condition and functionality declaration.
3.  **Packaging**
    -   Laptop-inside-box photograph.
    -   Accessories photograph, where relevant.
    -   Sealed-package photograph.
4.  **Shipping and delivery**
    -   Carrier.
    -   Tracking number.
    -   Carrier pickup confirmation.
    -   Pickup weight, if available.
    -   Insurance evidence, if required.
    -   Delivery and signature confirmation.
5.  **Verification and settlement**
    -   Verification findings.
    -   Outstanding requirements.
    -   Buyer inspection status.
    -   Dispute status.
    -   Payout eligibility and payout status.

### 9.2 Example seller evidence checklist

Illustrative transaction: `VF-2048`\
Product: Refurbished AI-development laptop\
Buyer: Maya Chen\
Transaction value: `$1,400`

  Evidence requirement            Example status
  ------------------------------- -----------------------
  Serial number                   Verified
  Product-condition photographs   Verified
  Provenance photograph           Verified
  Hardware specifications         Verified
  Condition declaration           Verified
  Packaging photographs           Verified
  Sealed-package photograph       Verified
  Insurance evidence              Verified, if required
  Tracking and pickup weight      Processing
  Proof of delivery               Required
  Buyer inspection                Not started
  Seller payout                   Not authorized

The workspace should show a clear explanation such as:

> Buyer payment is confirmed. Your product and packaging evidence have
> passed verification. Verifund is waiting for carrier-confirmed
> delivery and completion of the buyer inspection period. Seller payout
> is not yet authorized.

The Seller Agent can proactively notify the seller when evidence is
missing, rejected, or requires a clearer photograph. It should explain
the specific problem and the action needed rather than simply reporting
that verification failed.

------------------------------------------------------------------------

## 10. Backend architecture

A practical architecture separates evidence storage, evidence
verification, policy decisions, and payment execution.

``` text
Seller Agent / Fulfillment Workspace
                |
                v
          Evidence API
                |
                v
          Evidence Service
      (metadata, object storage,
       hashes, audit history)
                |
                v
        Verification Engine
      /        |          \
 Identity   Product    Fulfillment
 checks     checks      checks
      \        |          /
                v
          Policy Engine
   (agreement, inspection, disputes,
        payout eligibility)
                |
                v
      Settlement Coordinator
       (PayPal payout, webhook
        confirmation, reconciliation)
                |
                v
        Internal Ledger
```

### 10.1 Suggested service responsibilities

  -----------------------------------------------------------------------
  Service                             Responsibility
  ----------------------------------- -----------------------------------
  `evidence_service`                  Accept uploads, store metadata,
                                      create hashes, and preserve
                                      evidence history.

  `evidence_validator`                Validate file type, size, required
                                      fields, and basic completeness.

  `identity_verifier`                 Extract and compare serial numbers
                                      and transaction challenge codes.

  `product_verifier`                  Compare specifications and
                                      condition evidence with the
                                      agreement.

  `fulfillment_verifier`              Validate packaging, tracking,
                                      carrier acceptance, and delivery
                                      evidence.

  `dispute_service`                   Collect claims, evidence,
                                      decisions, and resolution records.

  `release_policy_engine`             Determine whether all payout
                                      conditions are satisfied.

  `settlement_coordinator`            Initiate payout, process provider
                                      webhooks, and reconcile the ledger.
  -----------------------------------------------------------------------

LangGraph can coordinate long-running workflows, retries, and
human-review checkpoints. Deterministic backend services should remain
responsible for evidence validation rules, transaction state
transitions, policy enforcement, and payout authorization. An LLM agent
may assist with explanations or evidence triage, but should not
independently release funds.

### 10.2 Evidence storage

Store the actual photographs, videos, and documents in object storage.
Store their metadata and references in Neon PostgreSQL.

For each evidence submission, retain: - Evidence ID. - Transaction ID. -
Seller or buyer ID. - Requirement type. - Object-storage reference. -
Original filename and media type. - File size. - Cryptographic hash. -
Submission timestamp. - Evidence source and simulation flag. -
Verification status. - Verification findings. - Reviewer identity and
decision, where applicable.

Do not overwrite historical evidence when a seller uploads a
replacement. Preserve the original submission and create a new evidence
record linked to the same requirement.

### 10.3 Suggested Neon PostgreSQL tables

  -----------------------------------------------------------------------
  Table                               Purpose
  ----------------------------------- -----------------------------------
  `fulfillment_tasks`                 Fulfillment task and overall status
                                      for a transaction.

  `fulfillment_requirements`          Evidence requirements generated for
                                      the transaction.

  `evidence_submissions`              Uploaded evidence metadata and
                                      object-storage references.

  `evidence_verifications`            Verification attempts, statuses,
                                      findings, and reviewer decisions.

  `product_identifiers`               Serial number, manufacturer, model,
                                      and device identity.

  `shipment_records`                  Carrier, tracking number, service,
                                      and shipment metadata.

  `carrier_events`                    Tracking events and timestamps.

  `delivery_confirmations`            Delivery time, signature reference,
                                      and proof-of-delivery reference.

  `inspection_records`                Buyer inspection status, decisions,
                                      and submitted evidence references.

  `disputes`                          Claims, evidence, status, and
                                      resolution.

  `settlement_records`                Payout amount, status, provider
                                      reference, and reconciliation data.
  -----------------------------------------------------------------------

Use database constraints and transactional state changes to prevent
duplicate payout authorization. Payout operations should be idempotent:
retries must not create multiple payouts for the same approved
settlement.

------------------------------------------------------------------------

## 11. Recommended laptop evidence policy

The following is a suggested baseline. The final requirement set should
be generated from the agreement and Verifund's configurable risk policy.

  -----------------------------------------------------------------------------
  Evidence                            Mandatory baseline? Verification approach
  -------------------------- ---------------------------- ---------------------
  Serial number                                       Yes Compare seller entry
                                                          with device evidence.

  Serial-number photograph                            Yes OCR plus visual
                                                          review if needed.

  Product-condition                                   Yes Completeness and
  photographs                                             image review.

  Transaction provenance                              Yes Challenge-code and
  photograph                                              expiry validation.

  Hardware specifications                             Yes Compare with the
                                                          transaction
                                                          agreement.

  Condition declaration                               Yes Schema validation and
                                                          agreement comparison.

  Battery report                When battery condition is Compare with declared
                                     material or promised threshold.

  BIOS/MDM/activation-lock       Yes for relevant devices Declaration plus
  declaration                                             available device
                                                          checks.

  Laptop-inside-package                               Yes Visual and identity
  photograph                                              continuity checks.

  Sealed-package photograph                           Yes Label and audit
                                                          continuity checks.

  Tracking number                  Yes for shipped orders Carrier lookup or
                                                          simulated carrier
                                                          lookup.

  Carrier pickup                                      Yes Carrier event
  confirmation                                            validation.

  Pickup weight                          Policy-dependent Anomaly detection.

  Shipping insurance                     Policy-dependent Coverage
                                                          confirmation.

  Proof of delivery                Yes for shipped orders Carrier
                                                          proof-of-delivery
                                                          validation.

  Signature                       Required for high-value Carrier confirmation.
                                      shipments if policy 
                                                specifies 

  Buyer inspection               Yes when required by the Buyer acceptance,
                                                agreement expiry, or dispute
                                                          resolution.
  -----------------------------------------------------------------------------

The policy engine should be able to change requirements based on: -
Product category. - Transaction value. - Seller risk profile. - Shipping
method. - Destination and delivery risk. - Product condition. - The
exact promises in the transaction agreement.

For example, if the seller promises a particular GPU, battery-health
threshold, warranty period, or accessory, that promise should become a
structured requirement that can be checked.

------------------------------------------------------------------------

## 12. Implementation recommendations and safeguards

1.  **Keep the evidence trail immutable.** Preserve original uploads,
    hashes, timestamps, verification attempts, and reviewer decisions.
2.  **Separate evidence from conclusions.** Store what the seller
    submitted separately from what Verifund concluded after
    verification.
3.  **Make every check explainable.** A failed check should identify the
    field or evidence item that failed and the next action.
4.  **Use confidence and review states.** OCR and image analysis can be
    uncertain. Route ambiguous or high-impact results to a human
    reviewer.
5.  **Do not overclaim what evidence proves.** A photograph does not
    prove package contents at carrier handoff; a tracking scan does not
    prove the correct laptop was delivered; a seller declaration is not
    independent verification.
6.  **Make payout idempotent.** A repeated webhook or workflow retry
    must not pay the seller twice.
7.  **Use signed or authenticated provider events.** Verify payment and
    payout webhooks according to the provider's current integration
    requirements.
8.  **Reconcile the ledger.** Compare internal transaction and
    settlement records with provider-confirmed payment and payout
    events.
9.  **Label simulation data.** Every mock carrier event, fixture image,
    generated diagnostic report, and simulated signature should be
    clearly marked as test data.
10. **Protect personal information.** Store only the delivery and
    recipient information required for the transaction and dispute
    process, with appropriate access controls and retention rules.
11. **Do not let an LLM make the final funds decision.** Agents can
    gather evidence, summarize findings, and request missing
    information. Deterministic policy checks and authorized settlement
    services should control payout.
12. **Define timeout and exception paths.** Missing delivery scans,
    failed delivery, returned packages, expired inspections, and
    unresolved disputes need explicit policy outcomes.

------------------------------------------------------------------------

## 13. End-to-end payout decision

The final decision should be produced from a complete, auditable
transaction record.

``` text
Is the laptop identity verified?
        |
        +-- No --> Block and request correction/review
        |
       Yes
        |
Do specifications and condition satisfy the agreement?
        |
        +-- No --> Block or open dispute
        |
       Yes
        |
Are packaging and shipment requirements verified?
        |
        +-- No --> Keep fulfillment incomplete
        |
       Yes
        |
Is delivery confirmed?
        |
        +-- No --> Wait, investigate, or apply timeout policy
        |
       Yes
        |
Is buyer inspection resolved?
        |
        +-- No --> Keep payout pending
        |
       Yes
        |
Is there an unresolved dispute or policy restriction?
        |
        +-- Yes --> Suspend payout
        |
        No
        |
Authorize seller payout
        |
        v
Initiate provider payout, confirm result,
and reconcile the internal ledger
```

## 14. Final recommendation

For laptop transactions, the **serial number should be the central
identity reference** across the original listing, seller evidence,
packaging evidence, and buyer inspection. It gives Verifund a consistent
way to investigate whether the device described in the agreement is the
device that was packaged and received.

The strongest implementation is not a collection of uploaded
photographs. It is a verifiable, chronological transaction record that
connects:

-   What the seller promised.
-   Which laptop the seller identified.
-   What condition and specifications were recorded.
-   What was placed in the package.
-   What the carrier accepted and delivered.
-   What the buyer inspected and accepted or disputed.
-   Why Verifund authorized, suspended, adjusted, or refused the seller
    payout.

In the simulated fulfillment demo, make every stage observable: evidence
submission, automated checks, human-review states, mock carrier events,
buyer inspection, policy evaluation, payout authorization, provider
confirmation, and ledger reconciliation. This demonstrates that Verifund
releases payment because the transaction's agreed conditions have been
satisfied---not simply because the seller uploaded files or a package
received a delivery scan.
