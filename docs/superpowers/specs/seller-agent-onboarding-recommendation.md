# Implementing Seller Agent Onboarding in Verifund

Seller Agent onboarding should be the process through which a seller registers their business, connects its commerce systems, provisions an autonomous Seller Agent, configures its permissions, and makes that agent discoverable to Buyer Agents through Verifund's Agent Registry.

The key architectural principle is:

A seller must onboard both as a business participant and as the owner of an autonomous agent. Registering an Agent Card alone does not establish that the seller is legitimate, that the agent belongs to the seller, or that it has authority to negotiate or accept transactions.

I recommend implementing onboarding as a guided, multi-stage workflow rather than a single registration form.

## 1. The complete onboarding lifecycle

1. Business registration

   Seller creates an organization account and provides business information.

2. Business verification

   Verifund verifies the seller's identity, business details, and authorized representatives as appropriate to the marketplace.

3. Commerce integration

   Seller connects product catalogs, inventory, pricing, order management, and communication channels.

4. Seller Agent provisioning

   Verifund creates the agent identity and associates it with the seller's tenant.

5. Agent configuration

   Seller configures capabilities, policies, negotiation limits, and delegated authority.

6. Agent testing

   Seller tests product discovery, quote generation, negotiation, and A2A communication in a controlled environment.

7. Registry publication and activation

   Verifund publishes approved Agent Card metadata and activates the agent for discovery by Buyer Agents.

The seller's onboarding status should be separate from the Seller Agent's operational status. For example, a business can be verified while its agent is still being configured.

## 2. Business registration and tenant creation

The first step is registering the seller as a Verifund organization.

When a seller creates an account, Verifund should create:

- A user identity for the person registering.
- A seller organization represented by a tenant.
- A membership connecting the user to the tenant.
- A seller profile containing business information.
- An onboarding record tracking progress.

For example:

```
{
  "tenant": {
    "id": "tenant_techsupply",
    "name": "TechSupply",
    "type": "ORGANIZATION",
    "status": "PENDING_VERIFICATION"
  },
  "membership": {
    "user_id": "user_001",
    "role": "OWNER"
  },
  "seller_profile": {
    "business_name": "TechSupply",
    "business_type": "ELECTRONICS",
    "country": "KE",
    "status": "PENDING_REVIEW"
  }
}
```

The seller registration form should collect information such as:

| Information                   | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Business name                 | Seller identity                          |
| Business type                 | Classification and marketplace discovery |
| Country and address           | Business location                        |
| Contact email and phone       | Communication                            |
| Website                       | Business profile                         |
| Authorized representative     | Authority to operate the account         |
| Business registration details | Verification, where applicable           |

Multi-tenancy consideration: The seller tenant owns the Seller Agent, catalog integrations, private inventory, pricing policies, and credentials. The buyer's tenant must not gain access to those private resources simply because its Buyer Agent negotiates with the Seller Agent.

## 3. Connect the seller's commerce systems

This is where onboarding becomes more than account creation.

A Seller Agent needs access to reliable seller information before it can respond to Buyer Agents. Verifund should therefore provide an integration step that lets sellers connect their existing commerce systems.

Commerce integrations

Illustrative seller integration setup

[Shopify](https://images.openai.com/static-rsc-4/NG7WKco8kW0CmVdH0gi8XZnxoX-676bgSaZ7DwV5dQH_Y3MVdoHhiWEGUtTNjAn031cLCzsXGhP5LCOm8Rv-OAVH0soh3sOv4U6effUomRcrZQqGa3qccBzx2uFTA6W89KI6s6QPBL8-Bw3mmfC8nfVAqYhOhkU1nqZEKJdwVQc?purpose=inline)

Shopify

Products, inventory, orders

Connect

[Woocommerce PNG Logo — Download Free Transparent Logo](https://images.openai.com/static-rsc-4/5WIWEA-kYyHX1P5sPtCD4vgEM9GnWGNEHKPyH8a2NrnWFoxNPSUbXFi8nupiDatZvPd1bz57-iu_pnH_wlJLNbErnz6vadztfqYPrk3ess6pR5NIlqJhFYT5OKQ0jVuCfLt50ja1A1mupQyzGJH-_lQwvWTlmeSjn2ScT8z8agg?purpose=inline)

WooCommerce

Product catalog and stock

Connect

[Stripe | Paiement en ligne | Blendy expert-comptable digital](https://images.openai.com/static-rsc-4/-BN2J44Ic5oN01xAC7UU8OuyapMHzQ4BCLwZSP4hbqVXxmcjVHyxD-DIno42ahGr9ESAPLLA3eHuBUTNfCPQpE-CFi-drs9A4Du3n3rHH-KpgOiuNHjvTz2fTYTv9l8kvPG93emOxXpq7RADWKgX3w_zzpF0rGiF48-IYy331zg?purpose=inline)

Payment configuration

Seller payment account configuration

Configure

[Slack Announces Record Third Quarter Fiscal Year 2020 Results | Slack](https://images.openai.com/static-rsc-4/9q1ZZLZIbwfOg83IlH6EfmKeI-oTtHuLs3gOMcZ45UAS6Xc0S0geAiQevRyc6L43ciuClGTcd0neSYisffr8hlVBOdvfrMdOpbVVS8c2p4cHZQlL6E2EWVj82LV52R99zzm_hX1smDECl4S2eaDfJXkzWmuw6aYFXT48rBujOrw?purpose=inline)

Slack

Seller notifications and communication

Connect

These are examples of possible integrations, not a claim that all are already supported.

The seller should also be able to upload a CSV catalog or manually create products when an integration is unavailable.

### What the Seller Agent needs access to

| Resource             | Agent capability                            |
| -------------------- | ------------------------------------------- |
| Product catalog      | Search and retrieve products                |
| Inventory            | Check stock and availability                |
| Pricing              | Retrieve permitted prices                   |
| Shipping             | Estimate delivery options                   |
| Product policies     | Explain warranties and returns              |
| Order management     | Retrieve and update authorized orders       |
| Seller communication | Notify the seller of requests and decisions |

I would implement these as tenant-scoped tools rather than giving the LLM direct database or commerce-platform access.

For example:

```
Seller Agent
    |
    v
Tool Authorization Gateway
    |
    +--> Catalog Service
    |
    +--> Inventory Service
    |
    +--> Pricing Service
    |
    +--> Shipping Service
    |
    +--> Order Service
```

Each tool call should verify the agent's identity, tenant ownership, permissions, and transaction scope.

## 4. Provision the Seller Agent

Once the seller has registered and connected its systems, Verifund can provision its autonomous agent.

I recommend treating the Seller Agent as a tenant-owned machine identity rather than simply creating an LLM configuration.

For example:

```
{
  "agent": {
    "id": "agent_techsupply_001",
    "tenant_id": "tenant_techsupply",
    "name": "TechSupply Seller Agent",
    "type": "SELLER",
    "status": "CONFIGURING"
  },
  "capabilities": [
    "catalog.search",
    "inventory.check",
    "pricing.quote",
    "offer.create",
    "offer.negotiate",
    "agreement.propose"
  ]
}
```

The important relationship is:

```
TechSupply Tenant
    |
    +── Seller Profile
    |
    +── Commerce Integrations
    |
    +── Seller Policies
    |
    +── Seller Agent
           |
           +── Agent Identity
           +── Credentials
           +── Agent Card
           +── Permissions
           +── Execution History
```

### Agent provisioning process

1. Verifund creates the agent record.
2. Assigns the agent to the seller's tenant.
3. Generates a unique agent identity.
4. Creates credentials and stores their secret material in a secrets manager.
5. Associates the agent with the seller's catalog and integrations.
6. Loads the seller's configured policies.
7. Registers the agent privately in the Agent Registry.
8. Marks it as `CONFIGURING`.

Credentials should not be stored as plaintext in the database. The database should contain references to the secrets manager.

## 5. Configure agent capabilities and negotiation policies

This is one of the most important onboarding steps.

The seller needs to decide what the Seller Agent can do independently and which decisions require human approval.

I would create a dedicated Agent Permissions and Negotiation configuration screen.

Seller Agent configuration

Product discovery

Enabled

Allow Buyer Agents to discover eligible products.

Generate quotations

Enabled

Generate quotes from authorized pricing data.

Negotiate offers

Enabled

Negotiate within seller-defined limits.

Accept agreements

Approval required

Require an authorized seller representative to approve contractual commitments.

Authorize payments

Restricted

Not part of ordinary Seller Agent negotiation authority.

### Example negotiation policy

Suppose TechSupply sells a refurbished laptop for $1,500.

The seller configures:

| Policy                   | Value   |
| ------------------------ | ------- |
| Listed price             | $1,500  |
| Minimum acceptable price | $1,350  |
| Maximum discount         | 10%     |
| Negotiation currency     | USD     |
| Quantity available       | 5       |
| Free shipping            | No      |
| Warranty                 | 90 days |

The Seller Agent can negotiate within these boundaries.

For example:

- Buyer Agent offers $1,250: Seller Agent rejects or counters.
- Buyer Agent offers $1,350: Seller Agent can accept the commercial offer if its policy permits.
- Buyer Agent offers $1,450: Seller Agent can accept or negotiate further.

However, an accepted commercial offer must not automatically mean that a legally binding agreement has been signed or that payment has been authorized.

Use three policy levels:

1. Tenant policy: What the seller's organization permits.
2. Agent policy: What this particular Seller Agent is allowed to do.
3. Run-level mandate: What the agent is permitted to do in one specific negotiation.

Effective authority must be the intersection of these permissions, not the broadest permission available.

## 6. Generate and publish the Seller Agent Card

Once the agent has been configured, Verifund should generate its A2A Agent Card.

The Agent Card is the public description that enables Buyer Agents to discover and understand the Seller Agent's capabilities.

For example:

```
{
  "name": "TechSupply Seller Agent",
  "description": "Autonomous sales agent for TechSupply",
  "url": "https://agents.verifund.com/techsupply/a2a",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "product_discovery",
      "name": "Product Discovery",
      "description": "Search available TechSupply products"
    },
    {
      "id": "price_negotiation",
      "name": "Price Negotiation",
      "description": "Negotiate product prices within seller policies"
    },
    {
      "id": "availability_check",
      "name": "Inventory Availability",
      "description": "Check current product availability"
    }
  ]
}
```

This card should be registered with your existing MarketMesh Agent Registry.

Your registry already handles Agent Cards, categories, hashes, and health checks. Extend it to associate each registered agent with a verified seller tenant.

I would separate public discovery information from private Verifund metadata.

| Public Agent Registry | Private Verifund records      |
| --------------------- | ----------------------------- |
| Agent ID              | Tenant ID                     |
| Display name          | Credential references         |
| Agent endpoint        | Negotiation policies          |
| Capabilities          | Internal permissions          |
| Product categories    | Seller integrations           |
| Agent Card hash       | Business verification records |
| Health status         | Internal agent configuration  |

The public Agent Card must not expose seller credentials, private inventory information, or internal tenant policies.

## 7. Test the Seller Agent before activation

Before publication, give the seller a test environment.

I recommend a test console that allows the seller to simulate a Buyer Agent making requests.

For example:

Seller Agent test console

Sandbox environment

BUYER AGENT REQUEST

"I am looking for a refurbished laptop with 32 GB RAM, 1 TB SSD, and a budget of $1,400. Can you offer a suitable product?"

SELLER AGENT RESPONSE

"I have a refurbished laptop matching those specifications. The listed price is $1,500. I can offer it for $1,400, including a 90-day warranty."

Test results

Agent authentication

Passed

Catalog retrieval

Passed

Pricing policy

Passed

A2A communication

Passed

Authority restrictions

Passed

Your tests should include:

- Agent authentication and identity validation.
- Catalog and inventory retrieval.
- Correct pricing and discount enforcement.
- Negotiation within configured boundaries.
- Rejection of unauthorized requests.
- A2A communication with a test Buyer Agent.
- Seller approval requirements.
- Agent suspension and credential revocation.

Only agents that pass the required tests should be eligible for activation.

## 8. Activate the Seller Agent

Once onboarding is complete, the seller can publish their agent.

I recommend this lifecycle:

| Status                 | Meaning                                  |
| ---------------------- | ---------------------------------------- |
| `CREATED`              | Agent record exists                      |
| `CONFIGURING`          | Seller is configuring capabilities       |
| `PENDING_VERIFICATION` | Required checks are outstanding          |
| `TESTING`              | Agent is undergoing validation           |
| `ACTIVE`               | Available for authorized A2A discovery   |
| `SUSPENDED`            | Temporarily unavailable                  |
| `REVOKED`              | Credentials and access have been revoked |

When the seller activates the agent:

1. Verifund confirms the seller's onboarding requirements.
2. Validates agent permissions and credentials.
3. Publishes the approved Agent Card.
4. Updates registry health and availability.
5. Makes the agent discoverable to Buyer Agents.
6. Records an activation event.

A suspended agent should not accept new transactions, but historical transactions and audit records should remain available.

## 9. How the Seller Agent participates in Verifund's A2A commerce workflow

Once active, the Seller Agent can participate in the buyer-seller negotiation workflow.

Buyer Agent

Searches for a product and submits an RFQ

MarketMesh Registry

Discovers and returns eligible Seller Agent Cards

Verifund Orchestrator

Authenticates agents, checks permissions, mediates A2A requests

Seller Agent — TechSupply

Checks catalog, inventory, pricing and seller policies

Negotiated Offer

Structured offer returned to Buyer Agent

Verifund Agreement Service

Creates versioned agreement and obtains required acceptances

Payment and Fulfillment

Payment processing, seller fulfillment and evidence verification

This should preserve your existing mediated A2A architecture:

- Buyer Agent requests go through the Orchestrator.
- The Orchestrator resolves the Seller Agent's trusted identity and credentials.
- Seller Agent receives an authenticated, scoped request.
- The response is validated before returning to the Buyer Agent.
- Seller credentials never enter LangGraph state, traces, or AG-UI.

### What happens after an agreement is approved?

The Seller Agent becomes the seller's operational assistant.

It can:

- Notify the seller that an order is ready.
- Explain the agreed fulfillment obligations.
- Send reminders about deadlines.
- Help the seller prepare evidence.
- Notify the seller about verification results.
- Request clarification when additional evidence is needed.

The actual fulfillment checklist should be generated from the approved agreement. The seller then uses the transaction-specific Fulfillment Workspace to submit evidence, monitor verification, and respond to requests.&#x20;

Explain PayPal Checkout UI.txt

This distinction is important: the Seller Agent guides the seller, while Verifund's backend remains authoritative for transaction and fulfillment state.

## 10. Backend implementation structure

For your FastAPI backend, I would organize seller onboarding as its own domain.

```
backend/app/
├── seller_onboarding/
│   ├── models.py
│   ├── schemas.py
│   ├── router.py
│   ├── service.py
│   ├── verification.py
│   ├── integrations.py
│   ├── progress.py
│   └── events.py
│
├── seller/
│   ├── profile.py
│   ├── catalog.py
│   ├── inventory.py
│   └── policies.py
│
├── agent_tenancy/
│   ├── provisioning.py
│   ├── identity.py
│   ├── credentials.py
│   ├── policies.py
│   ├── authorization.py
│   └── lifecycle.py
│
├── registry/
│   ├── agent_cards.py
│   ├── registration.py
│   ├── discovery.py
│   └── health.py
│
├── orchestrator/
│   ├── a2a_mediation.py
│   └── run_manager.py
│
└── integrations/
    ├── commerce/
    ├── messaging/
    └── payments/
```

### Suggested database tables

| Table                      | Responsibility                             |
| -------------------------- | ------------------------------------------ |
| `seller_profiles`          | Business information                       |
| `seller_verifications`     | Verification records                       |
| `seller_integrations`      | Connected commerce systems                 |
| `seller_catalogs`          | Catalog configuration                      |
| `seller_policies`          | Negotiation and operational policies       |
| `agents`                   | Seller Agent identity and ownership        |
| `agent_credentials`        | Secret references and credential lifecycle |
| `agent_runs`               | Execution records                          |
| `agent_cards`              | Published A2A metadata                     |
| `seller_onboarding_steps`  | Onboarding progress                        |
| `seller_onboarding_events` | Audit and lifecycle events                 |

Every seller-owned record should be tenant-scoped.

### Suggested API endpoints

```
# Seller registration
POST   /seller/onboarding
GET    /seller/onboarding/status
PATCH  /seller/profile

# Business verification
POST   /seller/verification/submit
GET    /seller/verification/status

# Commerce integrations
GET    /seller/integrations
POST   /seller/integrations
DELETE /seller/integrations/{integration_id}

# Seller Agent provisioning
POST   /seller/agents
GET    /seller/agents
GET    /seller/agents/{agent_id}
PATCH  /seller/agents/{agent_id}

# Agent configuration
PUT    /seller/agents/{agent_id}/capabilities
PUT    /seller/agents/{agent_id}/policies
GET    /seller/agents/{agent_id}/permissions

# Testing and activation
POST   /seller/agents/{agent_id}/test
POST   /seller/agents/{agent_id}/activate
POST   /seller/agents/{agent_id}/suspend

# Registry
GET    /registry/agents
GET    /registry/agents/{agent_id}
```

These are proposed application endpoints; the precise contracts should be finalized alongside your existing Registry API.

## 11. Recommended Next.js onboarding experience

For the frontend, I would create a dedicated seller onboarding wizard.

```
app/
└── seller/
    └── onboarding/
        ├── page.tsx
        ├── business/
        │   └── page.tsx
        ├── verification/
        │   └── page.tsx
        ├── integrations/
        │   └── page.tsx
        ├── agent-setup/
        │   └── page.tsx
        ├── permissions/
        │   └── page.tsx
        ├── testing/
        │   └── page.tsx
        └── activation/
            └── page.tsx
```

I would make each step independently saveable so sellers can leave and resume onboarding without losing their progress.

The onboarding dashboard should show completed steps, pending requirements, integration health, and agent activation status.

## 12. Recommended implementation order

I would build this in the following order:

| Phase | Implementation                                 | Priority  |
| ----- | ---------------------------------------------- | --------- |
| 1     | Seller tenant and business registration        | Essential |
| 2     | Seller profile and verification                | Essential |
| 3     | Catalog and inventory integration              | Essential |
| 4     | Seller Agent provisioning and identity         | Essential |
| 5     | Agent permissions and negotiation policies     | Essential |
| 6     | Agent Card generation and Registry integration | Essential |
| 7     | A2A sandbox testing                            | Essential |
| 8     | Agent activation and lifecycle management      | Essential |
| 9     | Seller fulfillment notifications and workspace | Next      |
| 10    | Advanced integrations and analytics            | Later     |

My recommendation: Build seller onboarding as a separate domain that provisions tenant-owned agents and integrates with your existing MarketMesh Registry. Don't make the Registry responsible for the entire business onboarding process. The seller onboarding service should own the workflow, while the Registry owns agent discovery and publication.

This separation gives Verifund a reusable architecture for onboarding many sellers, each with one or more independently configured Seller Agents.

A useful next step would be to turn this architecture into a complete implementation specification for the Seller Onboarding Service, including SQLAlchemy models, FastAPI endpoints, onboarding state transitions, and the Next.js wizard.
