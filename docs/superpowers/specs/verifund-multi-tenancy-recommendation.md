# Implementing Multi-Tenancy in Verifund

Multi-tenancy is one of the most important architectural decisions for Verifund because your platform is designed to support multiple buyers, sellers, businesses, personal AI agents, and independently operated Seller Agents.

I recommend implementing organization-based multi-tenancy with user-level identities, tenant-scoped agents, and transaction-level access control.

The goal is to make Verifund operate as one platform while ensuring that every buyer, seller, business, agent, conversation, transaction, and payment record belongs to the correct tenant and cannot be accessed by unauthorized tenants.

Let's look at how this fits into your existing Verifund architecture.

## 1. First, understand multi-tenancy in Verifund

Imagine Verifund has three businesses using the platform:

Tenant A — NovaTech Renewed

Seller

NovaTech organization

Organization ID: org_novatech

- Seller Agent
- Product catalog
- Inventory
- Pricing and negotiation mandates
- Seller messaging accounts
- Transactions and payouts

Tenant B — TechWorld Electronics

Seller

TechWorld organization

Organization ID: org_techworld

- Seller Agent
- Product catalog
- Inventory
- Pricing and negotiation mandates
- Seller messaging accounts
- Transactions and payouts

Tenant C — Individual Buyer

Buyer

Personal account

Organization ID: org_buyer_001

- Personal Shopping Agent
- Shopping preferences
- Shopping missions
- Negotiation history
- Payment and transaction history
- Messaging integrations

Shared Verifund Platform

Shared infrastructure, isolated tenant data, centralized transaction coordination

Each organization has its own data, agents, users, configurations, and permissions.

For example:

- NovaTech must not access TechWorld's product inventory or confidential pricing rules.
- TechWorld must not access NovaTech's negotiation history.
- A buyer must not access another buyer's private shopping preferences.
- A Seller Agent must not access a buyer's private conversation with their Buyer Agent.

However, these tenants must still be able to participate in the same transaction.

This is particularly important: multi-tenancy must not prevent cross-tenant commerce. It must allow authorized parties to collaborate without exposing their private organizational data.

## 2. Recommended tenancy model

I would use a hybrid model consisting of three identity levels.

### A. Platform level

This represents Verifund itself.

It manages:

- Platform administrators.
- Tenant registration.
- Subscription plans, if introduced.
- Global configuration.
- Agent registration and discovery.
- Platform-wide security policies.
- System monitoring.

### B. Organization level

An organization is the primary tenant boundary.

An organization can represent:

- An individual buyer.
- A seller or merchant.
- A marketplace.
- A business with multiple employees.
- An enterprise operating multiple Seller Agents.

For example, NovaTech Renewed is one organization, while its owner, employees, and Seller Agents belong to that organization.

### C. User level

Users belong to organizations through memberships.

A user can potentially belong to multiple organizations.

For example:

| User  | Organization   | Role              |
| ----- | -------------- | ----------------- |
| Alice | NovaTech       | Owner             |
| John  | NovaTech       | Inventory Manager |
| Sarah | NovaTech       | Sales Manager     |
| Alice | TechWorld      | Administrator     |
| Maya  | Personal Buyer | Buyer             |

Notice that Alice can belong to two organizations with different permissions.

This means you should not store a single `role` directly on the user record and assume that role applies everywhere.

Instead, use an organization membership model.

## 3. High-level multi-tenant architecture

I would introduce a dedicated Tenant and Identity layer into your existing architecture.

Verifund Users

Buyers · Sellers · Business Owners · Employees

Authentication and Identity

Login · OAuth · Sessions · User Identity

## Tenant Management Layer

Organization resolution · Membership · Roles · Permissions

Tenant A

NovaTech

Tenant B

TechWorld

Tenant C

Individual Buyer

Tenant-Aware Application Services

Buyer Agent · Seller Agent · Messaging · A2A Gateway · Marketplace · Transaction Services

Verifund Transaction Control Plane

Agreements · Approvals · Fulfillment · Disputes · Payment Policies · Ledger

Shared Infrastructure

NeonDB · Redis Streams · Object Storage · PayPal · Background Workers

The important architectural change is that tenant resolution happens before application services execute.

Every request should have an authenticated user identity and an authorized tenant context.

## 4. Database architecture and schema

For your current architecture, I recommend starting with:

- Neon PostgreSQL: shared multi-tenant relational database.
- Redis Streams: tenant-aware event processing and background jobs.
- Object storage: transaction documents, product images, fulfillment evidence.
- FastAPI: tenant-aware backend and authorization.
- Next.js 16: organization-aware frontend.
- LangGraph: agent orchestration with tenant-specific workflow state.

You do not need a separate database for every customer in the initial implementation.

Use a shared database and shared schema, with `tenant_id` on tenant-owned records.

This is commonly called a shared database, shared schema architecture.

### A. Core database tables

I would organize your database into the following groups.

Identity and tenant management

| Table                  | Responsibility                    |
| ---------------------- | --------------------------------- |
| `users`                | Global user identities            |
| `organizations`        | Individual and business tenants   |
| `organization_members` | User-to-organization membership   |
| `roles`                | Organization roles                |
| `permissions`          | Available permissions             |
| `invitations`          | Invitations to join organizations |

Agent management

| Table                | Responsibility                            |
| -------------------- | ----------------------------------------- |
| `agents`             | Buyer and Seller Agent identities         |
| `agent_mandates`     | Agent authority and operating constraints |
| `agent_memory`       | Tenant-specific agent memory              |
| `agent_credentials`  | References to protected agent credentials |
| `seller_agent_cards` | A2A Agent Cards and endpoints             |

Messaging

| Table                       | Responsibility                              |
| --------------------------- | ------------------------------------------- |
| `channel_accounts`          | Linked WhatsApp, Telegram, Discord accounts |
| `conversations`             | Messaging conversations                     |
| `messages`                  | Incoming and outgoing messages              |
| `conversation_participants` | Authorized conversation participants        |

Commerce and transactions

| Table                      | Responsibility                          |
| -------------------------- | --------------------------------------- |
| `products`                 | Seller product catalogs                 |
| `inventory`                | Seller inventory                        |
| `shopping_missions`        | Buyer shopping requests                 |
| `a2a_tasks`                | Agent-to-agent tasks                    |
| `offers`                   | Negotiation offers and counteroffers    |
| `agreements`               | Versioned commercial agreements         |
| `transactions`             | Authoritative transaction records       |
| `transaction_participants` | Buyer and seller access to transactions |
| `buyer_approvals`          | Transaction-specific approval records   |
| `fulfillment_evidence`     | Evidence and verification records       |
| `disputes`                 | Dispute management                      |

Payments and accounting

| Table              | Responsibility                           |
| ------------------ | ---------------------------------------- |
| `payment_accounts` | Tenant payment-provider account mappings |
| `payments`         | PayPal order and capture records         |
| `payouts`          | Seller payout records                    |
| `ledger_entries`   | Financial event history                  |
| `webhook_events`   | Incoming provider events                 |
| `audit_events`     | Security and transaction audit history   |

These tables extend the transaction model already established in your Verifund architecture.&#x20;

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt

### B. Example relational structure

Here is how the main relationships should work.

organizations

id · name · type

organization_members

organization_id · user_id · role

agents

organization_id · type · mandate

transactions

buyer_organization_id · seller_organization_id

transaction_participants

transaction_id · organization_id · role

agreements

transaction_id · version

payments

transaction_id · provider_id

fulfillment_evidence

transaction_id · evidence_status

The interesting part is the transaction relationship.

Suppose Maya belongs to `org_buyer_001`, while NovaTech belongs to `org_novatech`.

A transaction connects the two organizations:

```
transaction_id: vf_txn_2048

buyer_organization_id: org_buyer_001
seller_organization_id: org_novatech

status: FUNDS_HELD
agreement_version: 2
```

Both organizations can access the transaction, but they have different permissions.

| Information                      | Buyer   | Seller                 |
| -------------------------------- | ------- | ---------------------- |
| Product and agreed price         | Yes     | Yes                    |
| Agreement                        | Yes     | Yes                    |
| Buyer's private preferences      | Yes     | No                     |
| Seller's minimum pricing mandate | No      | Yes                    |
| Buyer's approval status          | Yes     | Authorized status only |
| Fulfillment evidence             | Yes     | Yes                    |
| Seller payout status             | Limited | Yes                    |

This is why I recommend a separate `transaction_participants` table.

A transaction is a shared business resource, not private data belonging exclusively to either organization.

## 5. Implement tenant isolation using PostgreSQL Row-Level Security

This is arguably the most important technical part of your implementation.

Simply adding `tenant_id` to database tables is insufficient.

For example, a developer might accidentally write:

```
transactions = await db.execute(    select(Transaction))
```

Without tenant filtering, this could return transactions belonging to every organization.

You could add a `WHERE tenant_id = ...` condition to every query, but eventually a developer or background worker will forget.

I recommend using PostgreSQL Row-Level Security (RLS) as a second enforcement layer.

PostgreSQL RLS restricts which rows a database role can read or modify, according to policies defined inside the database.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.postgresql.org&sz=32)

postgresql.org+1

### A. Add tenant_id to tenant-owned tables

For example:

```
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    organization_type TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE organization_members (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL
        REFERENCES organizations(id),
    user_id UUID NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,

    UNIQUE (organization_id, user_id)
);

CREATE TABLE agents (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL
        REFERENCES organizations(id),
    agent_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE products (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL
        REFERENCES organizations(id),
    name TEXT NOT NULL,
    price NUMERIC(12, 2) NOT NULL
);
```

Here, `tenant_id` identifies the organization that owns a product.

### B. Enable RLS

```
ALTER TABLE products
ENABLE ROW LEVEL SECURITY;

ALTER TABLE products
FORCE ROW LEVEL SECURITY;
```

Create a tenant isolation policy:

```
CREATE POLICY product_tenant_isolation
ON products
FOR ALL
USING (
    tenant_id =
    NULLIF(
        current_setting('app.tenant_id', true),
        ''
    )::UUID
)
WITH CHECK (
    tenant_id =
    NULLIF(
        current_setting('app.tenant_id', true),
        ''
    )::UUID
);
```

This means:

- A tenant can only read its own products.
- A tenant cannot update another tenant's products.
- A tenant cannot delete another tenant's products.
- A tenant cannot insert products belonging to another tenant.

### C. Set the tenant context from FastAPI

After authentication and membership validation, your backend establishes the tenant context for the database transaction.

```
from sqlalchemy import textasync def set_tenant_context(    db,    tenant_id: str):    await db.execute(        text(            """            SELECT set_config(                'app.tenant_id',                :tenant_id,                true            )            """        ),        {"tenant_id": tenant_id}    )
```

The third argument, `true`, makes the setting transaction-local.

Your database operations should run inside the same transaction:

```
async with db.begin():    await set_tenant_context(        db,        authorized_tenant_id    )    products = await db.execute(        select(Product)    )    result = products.scalars().all()
```

Important security considerations:

1. Never accept the tenant ID as authoritative simply because the frontend supplied it.
2. Resolve tenant membership using the authenticated user's identity.
3. Use a restricted application database role that does not own the tables or have `BYPASSRLS`.
4. Keep RLS context transaction-local to avoid leaking tenant context through pooled database connections.
5. Apply appropriate RLS policies to every tenant-owned table, including writes.
6. Test that missing tenant context results in denied access.

PostgreSQL documents the special behavior of table owners and privileged roles, so `FORCE ROW LEVEL SECURITY` and restricted database credentials matter.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.postgresql.org&sz=32)

postgresql.org+1

### D. Handle shared transactions with cross-tenant RLS

A normal tenant policy is not sufficient for transactions because a buyer and seller belong to different tenants.

For example, both `org_buyer_001` and `org_novatech` must access `vf_txn_2048`.

You can implement a transaction-specific policy:

```
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    buyer_organization_id UUID NOT NULL,
    seller_organization_id UUID NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE transactions
ENABLE ROW LEVEL SECURITY;

ALTER TABLE transactions
FORCE ROW LEVEL SECURITY;

CREATE POLICY transaction_participant_access
ON transactions
FOR SELECT
USING (
    buyer_organization_id =
        NULLIF(
            current_setting('app.tenant_id', true),
            ''
        )::UUID

    OR

    seller_organization_id =
        NULLIF(
            current_setting('app.tenant_id', true),
            ''
        )::UUID
);
```

This allows both organizations to access the shared transaction.

However, this is only the organization-level visibility check. Your application must additionally check user membership, transaction role, and action-specific permissions.

For example:

- Buyers can approve their agreements.
- Sellers can submit fulfillment evidence.
- Only authorized reviewers can resolve disputes.
- Only the payment service can initiate seller payouts.

You should also keep private information outside the shared transaction record. RLS filters rows, not individual columns.

For example, seller pricing mandates should remain in seller-private tables, not in the shared agreement or transaction record.

My recommendation: use two authorization mechanisms:

1. Tenant-level RLS for organization-owned records.
2. Transaction-level authorization for resources shared between buyer and seller organizations.

## 6. Make the Buyer Agent and Seller Agent tenant-aware

This is particularly important because Verifund is not just a conventional multi-tenant SaaS application.

You are building a platform where each organization can operate its own AI agents.

Consider this scenario:

- Maya registers on Verifund.
- NovaTech registers as a seller.
- TechWorld registers as another seller.
- Each seller configures its own Seller Agent.
- Maya has her own Personal Shopping Agent.

You should not create one global Buyer Agent that shares memory and mandates across all buyers.

Instead, create agent instances associated with their owners.

### A. Buyer Agent

Each buyer has an agent associated with their personal organization.

```
organizations
    |
    ├── org_maya
    |     |
    |     └── Buyer Agent
    |           ├── Shopping preferences
    |           ├── Shopping history
    |           ├── Budget mandates
    |           ├── Negotiation history
    |           └── Active missions
    |
    └── org_james
          |
          └── Buyer Agent
                ├── Shopping preferences
                ├── Shopping history
                ├── Budget mandates
                ├── Negotiation history
                └── Active missions
```

Each agent has its own:

- Agent identity.
- Memory namespace.
- Mandates.
- Workflow state.
- Tool permissions.
- Conversation history.

### B. Seller Agent

Every seller organization can provision one or multiple Seller Agents.

For example:

```
org_novatech
    |
    ├── Seller Agent — Electronics
    |      ├── Electronics catalog
    |      ├── Inventory
    |      └── Pricing mandates
    |
    └── Seller Agent — Accessories
           ├── Accessories catalog
           ├── Inventory
           └── Pricing mandates


org_techworld
    |
    └── Seller Agent — Main
           ├── Product catalog
           ├── Inventory
           └── Pricing mandates
```

The Seller Agent must retrieve its seller's pricing rules and inventory using the authenticated organization context.

The LLM should never decide which organization's inventory or pricing rules it can access.

### C. Agent memory isolation

This is an area that deserves special attention when using LangGraph.

For example, instead of storing agent memory under:

```
namespace = ("buyer_memory",)
```

Use:

```
namespace = (    "tenants",    str(tenant_id),    "agents",    str(agent_id),    "memory")
```

Similarly, workflow checkpoints should be associated with the correct tenant and agent.

```
checkpoint_config = {    "configurable": {        "thread_id": str(mission_id),        "tenant_id": str(tenant_id),        "agent_id": str(agent_id)    }}
```

The tenant and agent identifiers should be validated by your backend, not trusted from arbitrary workflow input.

This prevents one buyer's agent from retrieving another buyer's shopping history or another seller's private negotiation information.

## 7. Multi-tenancy in messaging integrations

Your messaging-first architecture introduces another important consideration.

Verifund allows users to interact with their agents through WhatsApp, Telegram, Discord, Slack, and other supported platforms.

You must establish a secure relationship between:

1. The messaging account.
2. The Verifund user.
3. The organization.
4. The agent.
5. The conversation.

I recommend the following structure:

```
channel_accounts
----------------
id
organization_id
user_id
provider
external_account_id
verification_status
created_at

conversations
-------------
id
organization_id
agent_id
channel_account_id
external_conversation_id
status

messages
--------
id
organization_id
conversation_id
external_message_id
content
direction
processing_status
created_at
```

### Example

Maya interacts with her Buyer Agent using Telegram.

NovaTech interacts with its Seller Agent using WhatsApp.

Maya

Telegram

Buyer Agent

org_maya

NovaTech

WhatsApp

Seller Agent

org_novatech

A2A Communication

Authenticated agent-to-agent negotiation

Verifund Transaction Control Plane

Shared transaction, isolated private information

The messaging gateway should resolve the incoming event to the correct user, organization, and agent before passing it to LangGraph.

For example:

```
async def process_incoming_message(event):    channel = await resolve_channel_account(        provider=event.provider,        external_account_id=event.account_id    )    user = await authenticate_channel_user(channel)    membership = await resolve_membership(        user_id=user.id,        organization_id=channel.organization_id    )    agent = await get_authorized_agent(        agent_id=channel.agent_id,        organization_id=membership.organization_id    )    return await run_agent(        agent=agent,        tenant_id=membership.organization_id,        message=event.message    )
```

The important part is that the incoming messaging identity must be verified before any agent receives the message.

Do not assume that a Telegram user ID or WhatsApp phone number is automatically a verified Verifund identity.

Explain Personal AI Agents.txt

## 8. Multi-tenancy in A2A communication

This is where Verifund's architecture becomes particularly interesting.

A2A enables independent Buyer Agents and Seller Agents to communicate without sharing the same framework or infrastructure.

But multi-tenancy introduces another requirement: agent identity must be connected to an authorized organization.

Consider two Seller Agents:

```
NovaTech
  |
  └── Seller Agent
       agent_id: agent_novatech
       tenant_id: org_novatech
       endpoint: https://novatech.example/a2a

TechWorld
  |
  └── Seller Agent
       agent_id: agent_techworld
       tenant_id: org_techworld
       endpoint: https://techworld.example/a2a
```

Both agents can publish A2A Agent Cards.

However, registering an Agent Card does not automatically establish trust.

Your A2A Gateway should implement:

- Agent registration and ownership verification.
- Endpoint verification.
- Authentication of incoming A2A requests.
- Agent-to-organization identity mapping.
- Capability and mandate validation.
- Request authorization.
- Task ownership and tenant association.
- Replay protection and request deduplication.

### Example A2A request context

When Maya's Buyer Agent contacts NovaTech:

```
{
  "requester": {
    "agent_id": "agent_maya",
    "tenant_id": "org_maya",
    "type": "buyer"
  },
  "recipient": {
    "agent_id": "agent_novatech",
    "tenant_id": "org_novatech",
    "type": "seller"
  },
  "task": {
    "task_id": "a2a_task_2048",
    "transaction_id": "vf_txn_2048",
    "operation": "request_quote"
  }
}
```

This is an illustrative application-level envelope, not a replacement for the A2A protocol's message structure.

The A2A Gateway should authenticate the sender and resolve its identity against Verifund's registered agent records.

Important: Do not allow a buyer to specify an arbitrary `tenant_id` and thereby impersonate another organization.

The gateway must derive the sender's tenant from verified credentials.

Your existing Seller Agent architecture already separates the A2A interface, agent orchestrator, seller policy engine, and Verifund transaction coordination. Multi-tenancy adds organization-aware identity and authorization to those boundaries.&#x20;

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt

## 9. Multi-tenant PayPal integration

This is another critical area.

Different sellers may have different PayPal merchant accounts or payout destinations.

For example:

| Organization | PayPal configuration    |
| ------------ | ----------------------- |
| NovaTech     | Merchant mapping A      |
| TechWorld    | Merchant mapping B      |
| Maya         | Buyer checkout identity |

I recommend a `payment_accounts` table.

```
CREATE TABLE payment_accounts (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    provider TEXT NOT NULL,
    provider_account_id TEXT NOT NULL,

    account_type TEXT NOT NULL,
    status TEXT NOT NULL,

    credentials_reference TEXT NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

The `credentials_reference` should point to a secret manager, not contain the actual PayPal secret.

### Payment workflow

The tenant-aware payment flow should look like this:

Buyer Agent

Creates a purchase request

Verifund Transaction Service

Validates agreement and buyer approval

Payment Orchestrator

Resolves the appropriate payment configuration

PayPal Integration

Creates and captures the buyer payment

Verifund Ledger

Records provider-confirmed financial events

Fulfillment Verification

Evaluates agreement requirements

Seller Payout

Uses the authorized seller recipient mapping

For your existing hackathon prototype, retain the previously defined model:

1. Buyer completes PayPal Sandbox checkout.
2. Verifund captures the payment into its Sandbox merchant account.
3. Verifund records the funds as held in its internal ledger.
4. Fulfillment evidence is verified.
5. Verifund initiates the separate seller payout.
6. The provider-confirmed result updates the ledger.

The multi-tenant extension means the seller recipient mapping and transaction ownership must be validated before payout.

Do not expose PayPal credentials to Buyer Agents or Seller Agents.

Also, do not interpret a Sandbox payment held in an internal ledger as a legally established real-world escrow arrangement.&#x20;

Explain Personal AI Agents.txt

## 10. Multi-tenancy in Redis, background workers, and storage

Your architecture also uses Redis Streams, NeonDB, and background processing. These components need tenant isolation too.

### A. Redis Streams

Avoid generic event identifiers that do not include tenant context.

For example:

```
agent_events
transaction_events
payment_events
fulfillment_events
```

Every event should carry its tenant and resource identifiers.

```
{
  "event_id": "evt_001",
  "event_type": "fulfillment.evidence_submitted",
  "tenant_id": "org_novatech",
  "transaction_id": "vf_txn_2048",
  "actor_id": "agent_novatech",
  "timestamp": "2026-11-05T20:00:00Z"
}
```

The worker must validate that the event actor is authorized for the specified organization and transaction.

Redis can use shared streams, provided every consumer enforces authorization and event ownership. You can introduce tenant-specific consumer groups or streams as volume grows.

### B. Object storage

Use tenant-aware storage paths:

```
verifund/
    tenants/
        org_maya/
            agent-memory/
            conversations/
            documents/

        org_novatech/
            products/
            fulfillment/
            documents/

        org_techworld/
            products/
            fulfillment/
            documents/
```

For shared transactions, you can use:

```
transactions/
    vf_txn_2048/
        agreements/
        payment-receipts/
        fulfillment-evidence/
        dispute-evidence/
```

The transaction files should have access policies based on transaction participation, not merely knowledge of the storage path.

Generate short-lived signed URLs only after authorization.

### C. Background workers

Every background job should carry:

- `tenant_id`
- `agent_id`, where applicable
- `transaction_id`, where applicable
- `initiated_by`
- `correlation_id`

For example, a payout reconciliation worker must not process a payout using another tenant's payment configuration.

## 11. Implement organization-based RBAC

Multi-tenancy and role-based access control (RBAC) work together.

You need to distinguish between:

- Who owns the data?
- Who belongs to the organization?
- What is that person's role?
- What operation are they permitted to perform?

I recommend the following initial roles.

| Role                | Permissions                               |
| ------------------- | ----------------------------------------- |
| Platform Admin      | Manage platform-wide configuration        |
| Organization Owner  | Manage organization and members           |
| Organization Admin  | Manage agents, integrations and settings  |
| Agent Manager       | Configure agent mandates and capabilities |
| Sales Manager       | Manage products, offers and orders        |
| Fulfillment Manager | Manage fulfillment and evidence           |
| Finance Manager     | View payment and payout records           |
| Buyer               | Manage personal shopping and approvals    |
| Reviewer            | Review authorized evidence and disputes   |

Avoid giving every organization administrator unrestricted financial permissions.

For example, a seller's Sales Manager might configure products and respond to negotiations but should not automatically be able to change PayPal payout destinations.

You can enforce permissions through a centralized authorization service.

```
async def authorize(    user_id: str,    organization_id: str,    permission: str):    membership = await get_membership(        user_id,        organization_id    )    if not membership:        raise PermissionError("Not a member")    allowed = await check_permission(        role=membership.role,        permission=permission    )    if not allowed:        raise PermissionError("Access denied")    return membership
```

For sensitive transaction operations, this check should also validate the user's relationship to the transaction and its current state.

## 12. Recommended backend project structure

I would organize the FastAPI backend around domain modules rather than scattering tenant checks throughout the application.

```
backend/
│
├── app/
│   ├── main.py
│   ├── config.py
│   │
│   ├── core/
│   │   ├── security.py
│   │   ├── authentication.py
│   │   ├── authorization.py
│   │   └── database.py
│   │
│   ├── tenancy/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── resolver.py
│   │   ├── middleware.py
│   │   ├── dependencies.py
│   │   └── permissions.py
│   │
│   ├── organizations/
│   │   ├── models.py
│   │   ├── service.py
│   │   └── routes.py
│   │
│   ├── agents/
│   │   ├── buyer/
│   │   ├── seller/
│   │   ├── memory/
│   │   └── mandates/
│   │
│   ├── messaging/
│   │   ├── gateway.py
│   │   ├── channel_resolver.py
│   │   └── adapters/
│   │
│   ├── a2a/
│   │   ├── gateway.py
│   │   ├── authentication.py
│   │   ├── registry.py
│   │   └── authorization.py
│   │
│   ├── commerce/
│   │   ├── products/
│   │   ├── inventory/
│   │   ├── missions/
│   │   └── offers/
│   │
│   ├── transactions/
│   │   ├── agreements.py
│   │   ├── approvals.py
│   │   ├── participants.py
│   │   └── service.py
│   │
│   ├── payments/
│   │   ├── paypal.py
│   │   ├── accounts.py
│   │   ├── payouts.py
│   │   └── reconciliation.py
│   │
│   ├── fulfillment/
│   ├── disputes/
│   ├── ledger/
│   ├── webhooks/
│   │
│   └── workers/
│       ├── event_processor.py
│       └── reconciliation_worker.py
│
├── migrations/
├── tests/
│   ├── tenancy/
│   ├── authorization/
│   ├── agents/
│   ├── a2a/
│   ├── transactions/
│   └── payments/
│
└── requirements.txt
```

The most important module here is `tenancy/`.

It should provide a reusable tenant context to the rest of your application.

For example:

```
class TenantContext:    tenant_id: str    user_id: str    membership_id: str    role: str    permissions: list[str]
```

Your endpoints and services should receive this context rather than independently resolving tenant identity.

## 13. Frontend implementation

Your Next.js frontend should also support organization switching.

For example, a user who belongs to multiple organizations should be able to switch between their personal buyer workspace and their business seller workspace.

[Enterprise Payment Solutions for Large Businesses | Stripe](https://images.openai.com/static-rsc-4/u5-iqW-2SSJTISm4woKyvyiBN9iejzIZpFXir66xvCn-kiSFo4SXCu0BXWweATrWo1_7vd1-975q0gBE0mqEXjP3Esaiifhzu2_0pQrKIP648CP351eVjVMeaqU4O2pORbEx_rVk86R-8qSsMeuFne_xtUcAqDm3zBkp_o2m6Q0?purpose=inline)

[stripe.com](https://stripe.com/enterprise?utm_source=chatgpt.com)

I would introduce these frontend routes:

```
app/
├── (auth)/
│   ├── login/
│   ├── register/
│   └── onboarding/
│
├── (dashboard)/
│   ├── layout.tsx
│   ├── workspace/
│   │   └── switch/
│   │
│   ├── [organizationSlug]/
│   │   ├── dashboard/
│   │   ├── agents/
│   │   ├── marketplace/
│   │   ├── negotiations/
│   │   ├── transactions/
│   │   ├── fulfillment/
│   │   ├── payouts/
│   │   ├── integrations/
│   │   └── settings/
│
└── api/
```

The active organization determines the workspace being displayed.

For example:

```
/dashboard/org-novatech/agents
/dashboard/org-novatech/fulfillment

/dashboard/org-maya/shopping
/dashboard/org-maya/transactions
```

Do not rely on the URL slug as an authorization mechanism. The backend must verify membership and permissions on every request.

## 14. Which multi-tenancy architecture should you choose?

There are three common database approaches.

| Architecture                      | Data isolation                    | Complexity |
| --------------------------------- | --------------------------------- | ---------- |
| Shared database, shared schema    | RLS and application authorization | Low        |
| Shared database, separate schemas | Schema-level separation           | Medium     |
| Separate database per tenant      | Stronger physical separation      | High       |

For Verifund, I recommend starting with the first approach.

Recommended for initial implementation

Shared NeonDB PostgreSQL database + shared schema + tenant_id + PostgreSQL RLS.

Why?

1. You can onboard multiple buyers and sellers without provisioning databases.
2. Your agents can communicate across organizations.
3. Your transaction system can maintain shared buyer-seller records.
4. Your database migrations remain manageable.
5. Your application can scale without introducing unnecessary infrastructure.

Neon also discusses database-per-tenant designs for cases requiring stronger isolation, independent scaling, and tenant-specific recovery. That is a possible future upgrade for enterprise customers.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://neon.com&sz=32)

Neon+1

One distinction: Neon infrastructure's internal concept of a database tenant is not the same as a Verifund customer organization. You should implement Verifund's tenant model explicitly in your application.

## 15. Recommended implementation phases

I would implement multi-tenancy in six phases.

1. Phase 1 — Identity and organization management
   - Create organizations and users.
   - Implement organization memberships.
   - Introduce organization roles and permissions.
   - Build registration and organization onboarding.
2. Phase 2 — Database isolation
   - Add tenant IDs to tenant-owned tables.
   - Implement PostgreSQL RLS.
   - Add tenant-aware database sessions.
   - Write cross-tenant isolation tests.
3. Phase 3 — Multi-tenant agents
   - Provision Buyer Agents per buyer organization.
   - Provision Seller Agents per seller organization.
   - Isolate agent memory and LangGraph checkpoints.
   - Implement tenant-specific mandates and tool permissions.
4. Phase 4 — Messaging and A2A
   - Link messaging identities to organizations.
   - Implement tenant-aware messaging resolution.
   - Register Seller Agents and Agent Cards.
   - Authenticate and authorize cross-tenant A2A requests.
5. Phase 5 — Commerce and payments
   - Implement cross-tenant transactions.
   - Introduce transaction participants.
   - Implement tenant-specific PayPal account mappings.
   - Secure fulfillment, payouts, webhooks and ledger access.
6. Phase 6 — Production hardening
   - Test unauthorized cross-tenant access.
   - Test Redis and background worker isolation.
   - Add audit logging and monitoring.
   - Implement backups, recovery and tenant lifecycle management.

### Essential tests before production

| Test scenario                                       | Expected result |
| --------------------------------------------------- | --------------- |
| NovaTech accesses TechWorld products                | Denied          |
| Maya accesses another buyer's mission               | Denied          |
| NovaTech accesses its own transactions              | Allowed         |
| NovaTech accesses its authorized shared transaction | Allowed         |
| NovaTech accesses another seller's pricing mandate  | Denied          |
| Seller Agent accesses buyer private memory          | Denied          |
| Unauthorized user initiates a payout                | Denied          |
| Background worker processes another tenant's event  | Denied          |

## 16. My final architecture recommendation

For Verifund, I would build multi-tenancy around the following principles:

| Component     | Multi-tenancy strategy                                      |
| ------------- | ----------------------------------------------------------- |
| Identity      | Global users with organization memberships                  |
| Organizations | One tenant per personal or business workspace               |
| Agents        | Tenant-owned agent instances                                |
| Agent memory  | Isolated namespaces                                         |
| LangGraph     | Tenant-aware workflow state                                 |
| Messaging     | Verified account-to-tenant mapping                          |
| A2A           | Authenticated agent-to-organization identity                |
| Products      | Seller-owned records                                        |
| Transactions  | Shared resources with participant authorization             |
| Payments      | Tenant-aware account mappings and centralized orchestration |
| Database      | Shared NeonDB with RLS                                      |
| Redis         | Tenant-aware events and jobs                                |
| Storage       | Tenant-aware object access policies                         |

The most important architectural distinction

Verifund should have two different security boundaries:

1. Tenant isolation: protects private organizational information, agent memory, mandates, products, and configurations.
2. Transaction collaboration: allows authorized buyers, sellers, their agents, and Verifund to participate in the same transaction.

These should never be confused.

Ultimately, I would position Verifund as a multi-tenant agentic commerce infrastructure, rather than simply a marketplace with multiple seller accounts.

That architecture allows you to eventually support thousands of independent businesses, individual buyers, externally hosted Seller Agents, and multiple messaging platforms without requiring each participant to operate inside the same organization.

The guiding principle: Every organization owns its agents and private data; Verifund owns the transaction coordination process; authorized participants share only the information required to complete a transaction.
