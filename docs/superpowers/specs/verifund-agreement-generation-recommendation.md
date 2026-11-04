# How Verifund should generate an agreement after A2A negotiation

The best approach is to make agreement generation a dedicated backend workflow that starts when the Buyer Agent and Seller Agent successfully complete negotiation and Verifund receives a valid, mutually accepted final offer.

The Verifund agent should not simply ask an LLM to write a contract from the conversation history. Instead, it should take the structured negotiation result, validate it, construct a canonical agreement, and present that agreement to the buyer for final approval.

There is one important distinction in the workflow:

- A2A negotiation approval: The buyer and seller agents have converged on the commercial terms.
- Buyer purchase approval: The actual buyer has reviewed and authorized the exact agreement.

The agreement should be generated between these two events. This ensures that the buyer approves a specific, complete agreement rather than approving a vague order summary.&#x20;

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt

## 1. The complete workflow

Buyer Agent ↔ Seller Agent

A2A negotiation, offers and counteroffers

Negotiation complete

Final Offer Accepted

Both agents accept the same offer version

Verifund Agreement Generation

Validate → Normalize → Build → Hash → Persist

Agreement HITL Card

Display the complete agreement in the buyer's chat

Buyer Reviews and Approves

Approval bound to agreement ID, version and digest

PayPal Checkout

Create order and complete payment

Fulfillment and Settlement Workflow

Evidence verification, disputes and release decisions

The key is that the Agreement Service takes over from free-form negotiation. It works with structured, persisted offer data rather than trying to reconstruct the deal from chat messages.&#x20;

Explain Personal AI Agents.txt

## 2. Step-by-step agreement generation

### Step 1: Receive the final A2A negotiation result

When negotiation finishes, Verifund should receive a structured event indicating that the final offer has been accepted.

For example:

```
{
  "event_type": "offer.accepted",
  "transaction_id": "vf_txn_2048",
  "offer_id": "offer_2048",
  "offer_version": 3,
  "buyer_agent_id": "buyer_agent_001",
  "seller_agent_id": "seller_agent_001",
  "buyer_acceptance": "ACCEPTED",
  "seller_acceptance": "ACCEPTED",
  "currency": "USD",
  "item_price": "1370.00",
  "shipping": "30.00",
  "quantity": 1,
  "status": "MUTUALLY_ACCEPTED"
}
```

This is an illustrative application event, not a standard A2A protocol schema.

Verifund should then:

1. Authenticate the sending agents.
2. Verify that both agents are authorized to negotiate for their respective parties.
3. Confirm that both accepted the same offer ID and version.
4. Retrieve the complete offer from the database.
5. Confirm that the offer has not expired.
6. Check that the seller still has the agreed stock.
7. Check that neither party has withdrawn its acceptance.

Important: Do not generate an agreement just because the agents' conversation appears to have reached a conclusion. Verifund needs a persisted acceptance event for the exact final offer.

### Step 2: Run the Agreement Validation Service

Before constructing the agreement, Verifund should validate the final offer against the buyer's and seller's mandates.

I would divide validation into seven categories.

| Validation category | What Verifund checks                                 |
| ------------------- | ---------------------------------------------------- |
| Parties             | Buyer and seller identities and authority            |
| Product             | Product ID, description, condition and quantity      |
| Pricing             | Item price, shipping, taxes, fees and final amount   |
| Buyer mandate       | Spending ceiling and purchasing restrictions         |
| Seller mandate      | Minimum price, warranty and fulfillment commitments  |
| Availability        | Stock and offer expiration                           |
| Protection terms    | Inspection, evidence, returns and dispute conditions |

For example, consider the negotiated laptop:

Final negotiated offer

[Dell Latitude 7430 Laptop: Core i7 12th Gen 512GB 32GB RAM, Iris Xe Wa – GreenGreenStore](https://images.openai.com/static-rsc-4/JkE_frLlCGuQjZY14lD_BZKENNT_GZ-7jV7K3MFqpps7NFqlsuSDo5ddjOH23zN2hQ21zbt0No_G2CY8r0wizHUnWm47N2zRh9JcrZS8weZLslXMH9sDGREmPtXvo2tC_yt97oRx7I8gmhQegoTjeoQJWvyvNJ8bl4BQx-c96ZE?purpose=inline)

Refurbished AI-development laptop

NovaTech · 32 GB RAM · 1 TB SSD

Product price$1,370.00

Shipping$30.00

Quantity1

Warranty90 days

Inspection48 hours

Agreed subtotal

# $1,400.00

Illustrative amounts. Applicable taxes and fees must be resolved before the final payable total is approved.

If the final payable amount is unknown, Verifund should not silently generate an approval-ready agreement with an incomplete total. It should first obtain the necessary tax and fee calculations.

If a validation fails, the workflow should stop and return the transaction for clarification, renegotiation, or human review.

### Step 3: Construct the canonical agreement

Once validation passes, Verifund's Agreement Service creates a structured agreement object.

This is where I recommend separating two responsibilities:

- Agreement Builder: Converts the validated offer and applicable policies into the agreement structure.
- Agreement Renderer: Converts that structure into the human-readable Agreement Card.

The agreement itself should be structured data, not an LLM-generated block of prose.

For example:

```
{
  "agreement_id": "agreement_2048",
  "transaction_id": "vf_txn_2048",
  "version": 1,
  "status": "PENDING_BUYER_APPROVAL",

  "parties": {
    "buyer_id": "buyer_001",
    "seller_id": "seller_001"
  },

  "offer_reference": {
    "offer_id": "offer_2048",
    "offer_version": 3
  },

  "product": {
    "product_id": "laptop_001",
    "name": "Refurbished AI-development laptop",
    "condition": "REFURBISHED",
    "quantity": 1,
    "specifications": {
      "ram": "32 GB",
      "storage": "1 TB SSD"
    }
  },

  "commercial_terms": {
    "currency": "USD",
    "item_price": "1370.00",
    "shipping": "30.00",
    "taxes": null,
    "fees": "0.00",
    "total": null
  },

  "seller_obligations": {
    "warranty_days": 90,
    "shipping_method": "TRACKED",
    "fulfillment_evidence_required": true
  },

  "inspection": {
    "duration_hours": 48,
    "start_condition": "DELIVERY_CONFIRMED",
    "requirements": [
      "PRODUCT_MATCHES_SPECIFICATIONS",
      "DELIVERY_CONFIRMED",
      "CONDITION_MATCHES_AGREEMENT"
    ]
  },

  "dispute_terms": {
    "enabled": true,
    "resolution_method": "VERIFUND_REVIEW"
  },

  "expires_at": "2026-11-04T12:00:00Z"
}
```

This is an illustrative schema. In the actual implementation, use the project's database models and policy definitions.

The important design principle is that the agreement captures the exact terms the agents negotiated, including the conditions Verifund will later use to evaluate fulfillment.

### Step 4: Generate the agreement's human-readable terms

Now the Verifund agent can help translate the structured agreement into readable explanations.

For example:

- Product: Seller agrees to deliver one refurbished laptop with 32 GB RAM and 1 TB SSD.
- Price: The agreed item price is $1,370, with $30 tracked shipping.
- Warranty: Seller provides a 90-day warranty.
- Delivery: Seller must provide tracked shipping evidence.
- Inspection: Buyer has 48 hours after confirmed delivery to inspect the product.
- Verification: Verifund checks submitted evidence against the agreed specifications and delivery conditions.
- Disputes: Disagreements follow the applicable Verifund review process.

I would use the LLM for this explanatory layer, not for determining the authoritative price, changing the negotiated terms, or inventing missing legal conditions.

The generated explanations should be checked against the structured agreement before being displayed.

### Step 5: Lock the agreement and calculate its digest

After the agreement has been validated and constructed, Verifund should create an immutable agreement version.

The process is:

1. Normalize the agreement data into a canonical representation.
2. Serialize it deterministically.
3. Compute a cryptographic SHA-256 digest.
4. Store the agreement and digest.
5. Record the accepted offer reference.
6. Mark the agreement as awaiting buyer approval.

For example:

```
Agreement ID: agreement_2048
Version: 1
Status: PENDING_BUYER_APPROVAL

Offer: offer_2048
Offer version: 3

Digest:
sha256:7f3a9e8d...9f1e
```

The digest allows Verifund to identify the exact agreement version that was presented and approved.

If a material term changes, Verifund must create version 2 and calculate a new digest. Version 1's approval must never automatically authorize version 2.&#x20;

Explain Personal AI Agents.txt

### Step 6: Persist the agreement and publish an event

Verifund should save the agreement before sending it to the buyer.

Suggested database entities:

| Entity                  | Responsibility                                     |
| ----------------------- | -------------------------------------------------- |
| `transactions`          | Overall commerce transaction                       |
| `offers`                | Negotiation offers and counteroffers               |
| `agreements`            | Canonical agreement versions                       |
| `agreement_terms`       | Structured agreement clauses, if stored separately |
| `agreement_acceptances` | Buyer and seller acceptance records                |
| `agreement_events`      | Agreement lifecycle history                        |
| `buyer_approvals`       | Authenticated buyer approval records               |

Then publish an event such as:

```
{
  "event_type": "agreement.locked",
  "transaction_id": "vf_txn_2048",
  "agreement_id": "agreement_2048",
  "agreement_version": 1,
  "agreement_digest": "sha256:7f3a9e8d...9f1e",
  "status": "PENDING_BUYER_APPROVAL"
}
```

This event allows the frontend, messaging adapter, and transaction workflow to react without coupling the Agreement Builder to the chat interface.

### Step 7: Deliver the Agreement Card as a HITL message

The chat interface should receive the persisted agreement and render the Agreement Card.

For example, the buyer's chat might show:

Verifund Shopping Agent

10:25 AM

I have completed the negotiation with NovaTech. Both agents accepted the final offer. I've prepared the agreement for your review.

VERIFUND AGREEMENT

Awaiting approval

VF-2048 · Version 1

Refurbished AI-development laptop

NovaTech · Quantity 1

Product + shipping$1,400.00

Warranty90 days

Inspection48 hours

Seller acceptance

Accepted

Buyer approval

Pending

Review full agreement

Approval applies to this agreement version only.

The card should support expanding the complete agreement, viewing terms and version history, and explicitly approving the exact version.

## 3. Which agent or service should actually generate the agreement?

I recommend using a dedicated Agreement Generation workflow, orchestrated by Verifund, rather than giving the entire responsibility to the Buyer Agent or Seller Agent.

Here is the separation of responsibilities:

| Component                  | Responsibility                                                    |
| -------------------------- | ----------------------------------------------------------------- |
| Buyer Agent                | Provides buyer requirements and negotiation context               |
| Seller Agent               | Provides seller-authorized offers and fulfillment commitments     |
| A2A Coordinator            | Tracks negotiation and records mutually accepted offers           |
| Agreement Generation Agent | Helps interpret terms and produce readable agreement explanations |
| Agreement Builder          | Constructs the authoritative structured agreement                 |
| Agreement Validator        | Checks commercial terms, mandates and completeness                |
| Agreement Policy Engine    | Applies approval and transaction rules                            |
| Agreement Service          | Versions, hashes, persists and publishes the agreement            |
| Chat Interface             | Renders the Agreement HITL Card                                   |

The LLM-based Agreement Generation Agent is useful, but it should not have unrestricted authority to create binding financial terms.

The Builder, Validator, and Policy Engine should enforce the rules through deterministic application code.

## 4. Recommended LangGraph workflow

Since your Verifund architecture uses LangGraph for workflow orchestration, I would implement agreement generation as a dedicated subgraph.

START

Receive mutually accepted offer

VALIDATE ACCEPTANCE

Verify identities, authority and accepted offer version

LOAD TRANSACTION

Retrieve offer, product, parties and mandates

VALIDATE TERMS

Check price, stock, taxes, delivery and protection terms

BUILD AGREEMENT

Construct canonical structured agreement

GENERATE EXPLANATIONS

Produce readable descriptions from validated terms

VALIDATE AGREEMENT

Check completeness and consistency

CANONICALIZE + HASH

Generate immutable version and digest

PERSIST AGREEMENT

Save agreement and publish agreement.locked

HITL: Buyer Agreement Approval

Wait for authenticated buyer decision

Approved

Proceed to checkout

Changes requested

Revise agreement

The workflow should pause for buyer approval rather than keeping an agent execution running while waiting for a human. Persist the workflow state and resume it when an authenticated approval or revision event arrives.

## 5. What happens if the buyer requests changes?

This is an important part of the design.

Suppose the buyer reviews the agreement and says:

> I want the inspection period extended from 48 hours to 72 hours.

Verifund should:

1. Interpret the buyer's requested change.
2. Check whether the seller's mandate allows the change.
3. Send a revised proposal to the Seller Agent if seller agreement is required.
4. Wait for the seller's acceptance.
5. Update the structured offer and agreement terms.
6. Generate a new agreement version.
7. Calculate a new digest.
8. Present the revised Agreement Card to the buyer.

For example:

| Agreement field   | Previous | Revised           |
| ----------------- | -------- | ----------------- |
| Version           | v1       | v2                |
| Inspection        | 48 hours | 72 hours          |
| Seller acceptance | Accepted | Awaiting/accepted |
| Buyer approval    | Pending  | Pending           |
| Digest            | Hash A   | Hash B            |

Do not overwrite version 1. Keep it as historical evidence of what was previously proposed.

## 6. Suggested implementation structure

I would organize this functionality as follows:

```
backend/
└── app/
    ├── workflows/
    │   └── agreement_generation/
    │       ├── graph.py
    │       ├── state.py
    │       └── nodes/
    │           ├── validate_acceptance.py
    │           ├── load_transaction.py
    │           ├── validate_terms.py
    │           ├── build_agreement.py
    │           ├── generate_explanations.py
    │           ├── validate_agreement.py
    │           ├── canonicalize_agreement.py
    │           └── persist_agreement.py
    │
    ├── agents/
    │   └── agreement_agent.py
    │
    ├── services/
    │   ├── agreement_service.py
    │   ├── agreement_builder.py
    │   ├── agreement_validator.py
    │   ├── agreement_versioning.py
    │   └── agreement_digest.py
    │
    ├── policies/
    │   └── agreement_policy.py
    │
    ├── schemas/
    │   ├── offer.py
    │   ├── agreement.py
    │   └── approval.py
    │
    └── events/
        ├── agreement_locked.py
        └── buyer_approval.py
```

The frontend should consume the agreement from an API or realtime event, rather than asking the LLM to construct the card itself.

## 7. Important distinction: agreement approval versus order approval

There are two possible meanings of "the order has been approved":

Scenario A — Both agents have approved the negotiated order.

This is the workflow described above: generate the agreement, show it to the buyer, and request final buyer approval.

Scenario B — The human buyer has already approved the exact order.

In this case, the agreement should ideally have been generated and presented before that approval. If the buyer has already given authenticated approval to an exact, complete order representation, Verifund can generate and lock the corresponding agreement while preserving the approval's exact scope. It must not treat a vague chat confirmation as sufficient.

My recommendation is Scenario A because it gives Verifund a clear audit trail and makes the Agreement HITL Card the explicit boundary between autonomous negotiation and human-authorized purchasing.

## 8. My recommended design decision

Treat agreement generation as a Verifund-controlled transaction workflow with an LLM-assisted drafting capability, not as an autonomous contract-writing agent.

The critical sequence should be:

1. Buyer Agent and Seller Agent finish A2A negotiation.
2. Verifund records the mutually accepted final offer.
3. Agreement Service validates all negotiated terms.
4. Agreement Builder constructs the structured agreement.
5. Agreement Agent generates readable explanations.
6. Verifund validates, versions, hashes and persists the agreement.
7. Agreement HITL Card is delivered to the buyer's chat.
8. Buyer explicitly approves the exact agreement version.
9. Verifund proceeds to PayPal checkout.

This design also makes it possible to reuse the same Agreement Service for purchases initiated through Discord, Slack, WhatsApp, or Verifund's own marketplace UI.

The central architectural principle is: agents negotiate; Verifund validates and formalizes; humans authorize; payment services execute.&#x20;

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt
