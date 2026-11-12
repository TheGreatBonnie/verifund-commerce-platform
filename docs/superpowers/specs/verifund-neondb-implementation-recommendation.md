# Using Neon PostgreSQL as the relational database in Verifund

For Verifund, I recommend using Neon as the primary relational database and authoritative source of truth for the entire transaction lifecycle.

Neon will store the information that makes Verifund's agentic commerce workflows reliable: buyers, sellers, shopping missions, A2A negotiations, offers, agreements, buyer approvals, transactions, PayPal payment records, fulfillment evidence, payouts, disputes, and audit logs.

The important architectural decision is that Neon should not simply be used to store user accounts and marketplace products. It should underpin Verifund's transaction coordination, financial recordkeeping, and long-running agent workflows.

This fits the architecture we've established for Verifund:

- Next.js 16 + TypeScript: Buyer marketplace, seller workspace, negotiation interface, and administration dashboard.
- FastAPI: Backend API and business logic.
- LangGraph: Stateful buyer-agent workflows, negotiation orchestration, and human approval checkpoints.
- A2A: Communication between independent buyer and seller agents.
- Neon PostgreSQL: Persistent relational data and authoritative transaction state.
- Redis Streams: Realtime event processing and background communication.
- PayPal: Payment processing, capture, payouts, and refunds through supported APIs.
- Object storage: Product images, uploaded documents, shipping evidence, and other files.

## 1. What Neon does in Verifund

[Dynamically scale your Postgres database — Neon](https://images.openai.com/static-rsc-4/9ezSyH0YJ-YK2aoXoUpS9Q6HqEB25J3-dtkoi0IasAZWwZ7CeO6DP94fu2OcV8WcwYRgwBLCp5L88twHTzG_EaEdpXBEpA_jCxcvwVS62ALqQHJPxrbIUTeKbaFTPrOeZ8--dKyPT86tGjWAxd4n_u9iHWPNU6x6c_c4IfI3c4o?purpose=inline)

Neon PostgreSQL is a managed PostgreSQL service. It provides standard PostgreSQL connectivity, database branching, and connection pooling.

You can use ordinary PostgreSQL tools and libraries, including SQLAlchemy, Psycopg, Prisma, and Drizzle.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com&sz=32)

GitHub+2

I would give Neon five primary responsibilities.

| Responsibility          | What Neon stores                                    |
| ----------------------- | --------------------------------------------------- |
| Identity and tenancy    | Buyers, sellers, organizations, memberships, agents |
| Marketplace             | Products, catalogs, shopping missions               |
| Agentic commerce        | A2A tasks, negotiations, offers, agreements         |
| Transaction management  | Approvals, orders, payments, evidence, disputes     |
| Financial recordkeeping | Ledger entries, payouts, refunds, audit history     |

The most important principle: Neon stores the authoritative state of a transaction. An agent's conversation history, Redis messages, and PayPal webhook notifications should never independently determine whether a transaction is approved or whether funds can be released.

For example, when the Seller Agent accepts a buyer's counteroffer, Verifund should persist that offer and its version in Neon before treating the agreement as an established commercial commitment.

Similarly, a PayPal webhook must be validated and reconciled before the corresponding payment state is updated.

## 2. Overall database architecture

I recommend the following architecture:

Next.js 16 Frontend

Buyer interface · Seller workspace · Admin dashboard

FastAPI Backend

Authentication · API routes · Business logic · Authorization

## Verifund Application Services

LangGraph

A2A Gateway

Transaction Engine

PayPal Adapter

Neon PostgreSQL

Persistent relational records, transactions, ledger and checkpoints

Redis Streams

Event delivery, background processing and realtime updates

External services

PayPal APIs · Messaging platforms · Seller systems · Object storage

The components have separate responsibilities:

- FastAPI reads and writes application records in Neon.
- LangGraph persists workflow checkpoints so agents can resume after interruptions.
- A2A tasks and negotiation artifacts are recorded in Neon.
- Redis Streams distributes events to background workers.
- PayPal remains the authority for actual payment-provider outcomes.
- Neon records those outcomes and connects them to Verifund transactions.

This architecture also means that if Redis restarts or an agent process crashes, Verifund can recover from its durable database records.

## 3. Design the Verifund relational database

I would organize the database around functional domains rather than putting everything into a few enormous tables.

Here is the recommended schema.

### A. Identity and multi-tenancy

These tables manage the people, organizations, and agents using Verifund.

| Table                  | Purpose                                                   |
| ---------------------- | --------------------------------------------------------- |
| `users`                | User accounts and identity references                     |
| `organizations`        | Buyer organizations and seller businesses                 |
| `organization_members` | Membership and organization roles                         |
| `buyer_profiles`       | Buyer preferences and shopping settings                   |
| `seller_profiles`      | Seller business information                               |
| `buyer_agents`         | Buyer agent configuration                                 |
| `seller_agents`        | Seller agent configuration and A2A endpoints              |
| `agent_mandates`       | Agent permissions and spending or negotiation limits      |
| `connected_channels`   | WhatsApp, Telegram, Slack and other messaging connections |

For example, a seller organization might have multiple employees, products, and Seller Agents. They should all belong to the appropriate organization.

I recommend using a shared PostgreSQL database with a `tenant_id` on tenant-owned records.

This gives you one database while maintaining logical isolation between marketplace participants.

### B. Marketplace and product discovery

These tables support the agentic marketplace.

| Table                  | Purpose                                |
| ---------------------- | -------------------------------------- |
| `products`             | Product information                    |
| `product_variants`     | Product configurations and variants    |
| `product_categories`   | Product categories                     |
| `seller_products`      | Products listed by individual sellers  |
| `inventory`            | Stock quantities and availability      |
| `shopping_missions`    | Buyer's shopping requests              |
| `mission_requirements` | Structured shopping constraints        |
| `product_candidates`   | Products discovered by the Buyer Agent |

For example, when a buyer asks:

"Find me a refurbished laptop under $1,500 with 32 GB RAM."

The Buyer Agent creates a shopping mission, and the mission requirements are persisted in Neon.

The Product Discovery Agent can then search Channel3 or connected seller catalogs and save the results.

### C. A2A negotiation and agreements

This is one of the most important database domains in Verifund.

| Table                  | Purpose                                     |
| ---------------------- | ------------------------------------------- |
| `a2a_tasks`            | A2A task identifiers and lifecycle          |
| `a2a_messages`         | Agent communication records                 |
| `a2a_artifacts`        | Structured outputs and artifact references  |
| `negotiation_sessions` | Negotiation between buyer and seller agents |
| `offers`               | Structured offers and counteroffers         |
| `offer_versions`       | Immutable offer revisions                   |
| `agreements`           | Final agreed commercial terms               |
| `agreement_versions`   | Versioned agreement snapshots               |

You need these records because an agent-to-agent negotiation is not just a conversation.

For example:

1. Buyer Agent requests a laptop for $1,300.
2. Seller Agent counters at $1,450.
3. Buyer Agent offers $1,400.
4. Seller Agent accepts.
5. Verifund validates the agreement.
6. Verifund locks the final agreement version.

The database must preserve the entire negotiation history.

Most importantly, an agreement should contain a snapshot of the exact terms accepted by both sides.

Changing an agreement after buyer approval must invalidate the previous approval when the change is material.

### D. Transaction management

| Table                      | Purpose                                       |
| -------------------------- | --------------------------------------------- |
| `transactions`             | Main transaction records                      |
| `transaction_participants` | Buyer, seller and relevant participants       |
| `buyer_approvals`          | Approval records bound to agreement versions  |
| `transaction_events`       | Transaction lifecycle events                  |
| `transaction_requirements` | Fulfillment and settlement conditions         |
| `transaction_documents`    | Agreement and transaction document references |

This domain connects the commercial agreement with the actual protected transaction.

For instance, a transaction can reference:

- The buyer.
- The seller.
- The accepted offer.
- The agreement version.
- The buyer's authorization.
- The PayPal payment.
- The fulfillment requirements.
- The final settlement outcome.

### E. PayPal and financial records

| Table                    | Purpose                              |
| ------------------------ | ------------------------------------ |
| `payments`               | PayPal order and capture information |
| `payment_attempts`       | Payment execution attempts           |
| `ledger_accounts`        | Internal accounting accounts         |
| `ledger_entries`         | Append-only financial events         |
| `payouts`                | Seller payout records                |
| `refunds`                | Refund requests and outcomes         |
| `webhook_events`         | Received and processed PayPal events |
| `reconciliation_records` | Payment-provider reconciliation      |

I would pay particular attention to `ledger_entries`.

For Verifund, the ledger must preserve financial events rather than simply storing a mutable `balance` field.

A correction should be represented by a new ledger entry rather than silently changing an earlier financial record.

Your prototype's internal held-funds representation must also be distinguished from actual legally safeguarded escrow funds.

### F. Fulfillment, evidence and disputes

| Table                    | Purpose                               |
| ------------------------ | ------------------------------------- |
| `fulfillment_tasks`      | Seller fulfillment obligations        |
| `fulfillment_evidence`   | Evidence metadata and file references |
| `evidence_verifications` | Verification results                  |
| `delivery_records`       | Carrier and tracking information      |
| `inspection_records`     | Buyer inspection information          |
| `disputes`               | Buyer or seller disputes              |
| `dispute_evidence`       | Evidence submitted during disputes    |
| `dispute_resolutions`    | Review outcomes and remedies          |

This domain connects the fulfillment workspace to the transaction's settlement conditions.

For example, when a seller uploads a laptop diagnostic report, the actual file should be stored in object storage. Neon stores its URL or storage key, associated transaction ID, evidence type, hash, submission time, and verification status.

## 4. How the tables connect

The database should use relational relationships and foreign keys to preserve consistency.

Here is a simplified representation of the most important relationships:

organizations

tenant_id · id · name · type

usersorganization_members

agentsbuyer_agents · seller_agents

shopping_missions

Buyer requirements and mandates

negotiation_sessions

A2A tasks · messages · offers

agreements

Immutable versions · agreed terms

transactions

Central transaction record

buyer_approvals

payments

fulfillment_evidence

disputes

ledger_entries

payouts

The `transactions` table is the central relationship point.

It should not duplicate all the information contained in the other tables. Instead, it references the agreement, buyer, seller, and related payment records.

This makes it possible to retrieve a complete transaction history without putting every operation into one table.

## 5. Implement Neon multi-tenancy

Because Verifund supports independent buyers, sellers, and organizations, I recommend implementing multi-tenancy at the database level.

Use a shared-schema architecture:

```
Neon PostgreSQL
│
├── organizations
│   ├── Organization A
│   ├── Organization B
│   └── Organization C
│
├── users
├── organization_members
├── seller_profiles
├── buyer_profiles
├── products
├── agents
├── negotiations
├── agreements
├── transactions
├── payments
└── ledger_entries
```

Most tenant-owned tables should contain:

```
tenant_id UUID NOT NULL
```

For example:

```
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    organization_type TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    tenant_id UUID NOT NULL
        REFERENCES organizations(id),

    buyer_id UUID NOT NULL,
    seller_id UUID NOT NULL,

    agreement_id UUID NOT NULL,

    status TEXT NOT NULL DEFAULT 'PENDING',

    currency CHAR(3) NOT NULL,
    total_amount NUMERIC(19, 4) NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

You should also implement PostgreSQL Row-Level Security (RLS).

For example:

```
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_transactions
ON transactions
USING (
    tenant_id = current_setting(
        'app.current_tenant',
        true
    )::UUID
)
WITH CHECK (
    tenant_id = current_setting(
        'app.current_tenant',
        true
    )::UUID
);
```

Your FastAPI authentication middleware should:

1. Authenticate the user.
2. Identify their active organization.
3. Verify their membership and permissions.
4. Set the tenant context within the database transaction.
5. Execute database operations under that context.

Important: With Neon connection pooling, set tenant context transaction-locally, using `SET LOCAL` or `set_config(..., true)` inside the same database transaction. Never rely on a session-level tenant setting persisting across pooled connections.

Also, don't assume that every transaction has only one tenant. In Verifund, a buyer and seller may belong to different organizations. Model the transaction's buyer and seller organizations explicitly, and enforce access for both participants through an authorization policy. A single `tenant_id` is appropriate for an organization's private records, but the shared transaction record needs a deliberate cross-tenant access model.

For financial records, I would use stricter database permissions than for ordinary marketplace data.

## 6. Connect Neon to the FastAPI backend

This is where you integrate Neon into your application.

I recommend:

- SQLAlchemy 2.x for ORM and database operations.
- Psycopg 3 for PostgreSQL connectivity.
- Alembic for database migrations.
- Pydantic for request and response validation.

Why this combination?

Your backend is Python-based, and SQLAlchemy works well with FastAPI and complex relational models.

### Step 1: Create your Neon project

[Deploy a Serverless FastAPI App with Neon Postgres and AWS App Runner at any scale - Neon](https://images.openai.com/static-rsc-4/K4v-RH8wiVcbKLSejW21EaXePYEclksqUeDhSbvF7d4vQMs3KUn0ZcBUtBhrmV3xDAPk0uoOlgduz5INEAT90A6i7LRsqKgbECo_uIJ18GlmG5d0qeDIVwItyMhx7N8Wa6TM1qVkYszmZhrAmWIR-NdYE-dEJ1xBg6tqlBFNBZI?purpose=inline)

[neon.com](https://neon.com/blog/deploy-a-serverless-fastapi-app-with-neon-postgres-and-aws-app-runner-at-any-scale?utm_source=chatgpt.com)

Go to [Neon Console](https://console.neon.tech/?utm_source=chatgpt.com).

1. Create a new project named `verifund`.
2. Select your preferred cloud region.
3. Create the default PostgreSQL database.
4. Create an application database role.
5. Open the Connect dialog.
6. Select your branch, database, and role.
7. Copy the connection strings.

Neon provides pooled and direct connection strings.

You should configure both.

| Environment variable    | Purpose                                                        |
| ----------------------- | -------------------------------------------------------------- |
| `DATABASE_URL`          | Pooled application connections                                 |
| `DATABASE_URL_UNPOOLED` | Direct connection for migrations and administrative operations |

The pooled hostname contains `-pooler`. Neon recommends pooled connections for applications with many concurrent connections and direct connections for operations that require session-level behavior, such as migrations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com&sz=32)

GitHub+2

### Step 2: Install the dependencies

For your FastAPI backend:

```
uv add \
  fastapi \
  uvicorn \
  sqlalchemy \
  "psycopg[binary]" \
  alembic \
  pydantic-settings
```

### Step 3: Configure environment variables

Create your backend `.env`:

```
DATABASE_URL="postgresql+psycopg://USER:PASSWORD@YOUR-POOLER-HOST/neondb?sslmode=require"

DATABASE_URL_UNPOOLED="postgresql+psycopg://USER:PASSWORD@YOUR-DIRECT-HOST/neondb?sslmode=require"
```

Use the actual connection strings supplied by Neon, preserving its security parameters.

Never commit this file to GitHub.

### Step 4: Create the database connection

Create:

`app/database/session.py`

```
import osfrom sqlalchemy import create_enginefrom sqlalchemy.orm import sessionmaker, DeclarativeBaseDATABASE_URL = os.environ["DATABASE_URL"]engine = create_engine(    DATABASE_URL,    pool_pre_ping=True,    pool_size=5,    max_overflow=5,)SessionLocal = sessionmaker(    bind=engine,    autoflush=False,    expire_on_commit=False,)class Base(DeclarativeBase):    passdef get_db():    db = SessionLocal()    try:        yield db    finally:        db.close()
```

This gives you a reusable SQLAlchemy database session for your FastAPI endpoints.

For example:

```
from fastapi import APIRouter, Dependsfrom sqlalchemy.orm import Sessionfrom app.database.session import get_dbrouter = APIRouter()@router.get("/transactions")def get_transactions(    db: Session = Depends(get_db),):    return db.execute(        text("SELECT * FROM transactions")    ).mappings().all()
```

Add `from sqlalchemy import text` to the imports in this example. In production, replace unrestricted queries with authenticated, tenant-scoped repository methods and pagination.

### Step 5: Configure Alembic migrations

Initialize Alembic:

```
uv run alembic init migrations
```

Configure the migration environment to use `DATABASE_URL_UNPOOLED`.

For example, in `alembic.ini`, use a placeholder rather than committing a real connection string, and load the direct connection from your application settings in `migrations/env.py`.

Your workflow becomes:

```
# Generate a migration
uv run alembic revision --autogenerate \
  -m "create transaction tables"

# Apply migrations
uv run alembic upgrade head
```

I recommend using migrations from the beginning rather than manually creating production tables in the Neon Console.

## 7. How Neon supports the Verifund transaction lifecycle

This is where the database becomes particularly important.

Let's use the existing Verifund scenario: Maya wants to purchase a refurbished laptop from NovaTech Renewed.

Example transaction

VF-2048

[HP RENEW EliteBook 665 G11 laptop — Ryzen 7, 16GB, 512GB | AiO.lv](https://images.openai.com/static-rsc-4/2iURZQvgqGnAl6VpqHezhVbZDPLDIP8L_xR7OQY5K3SrbGOTSEA_aaFR5K9mv00yYtr2-JM5zdeA0AC7TvSsbP8UoEXM_5qaugioRI8Msbz8Bzt0f-hES6-bga18Jum6n6VeOZwLdEp-FDwMXkVW7nUteNNbP3hPo7bXcd5DXTo?purpose=inline)

Refurbished AI-development laptop

Buyer: Maya · Seller: NovaTech Renewed

# $1,400.00

1. Shopping mission created

   `shopping_missions` stores Maya's product requirements, spending limit, and shopping preferences.

2. A2A negotiation begins

   `a2a_tasks`, `negotiation_sessions`, and `offers` store the communication references, offers, and counteroffers.

3. Agreement established

   `agreements` and `agreement_versions` store the accepted terms, total amount, warranty, delivery requirements, and inspection conditions.

4. Buyer approval

   `buyer_approvals` stores Maya's authenticated approval, timestamp, and exact agreement version approved.

5. PayPal payment

   `payments` stores the PayPal order ID, capture ID, amount, currency, and provider-confirmed status.

6. Seller fulfillment

   `fulfillment_tasks` and `fulfillment_evidence` store the seller's fulfillment obligations and submitted evidence.

7. Verification

   `evidence_verifications` records whether the evidence passes, requires review, or fails.

8. Seller payout

   `payouts` and `ledger_entries` preserve the payout request, provider response, and associated financial events.

9. Transaction completion

   `transaction_events` and `audit_events` preserve the final outcome and transaction history.

The database provides continuity across the entire workflow.

For example, suppose the Seller Agent crashes after accepting Maya's counteroffer. When it restarts, it can retrieve the existing negotiation session and accepted offer from Neon instead of starting the negotiation again.

Likewise, if a PayPal webhook is delivered twice, Verifund can recognize that the event has already been processed.

### Recommended transaction states

Keep your transaction state machine explicit:

```
NEGOTIATING
    |
    v
AGREEMENT_PENDING
    |
    v
AWAITING_BUYER_APPROVAL
    |
    v
PAYMENT_PENDING
    |
    v
PAYMENT_CONFIRMED
    |
    v
FULFILLMENT_PENDING
    |
    v
UNDER_VERIFICATION
    |
    v
RELEASE_ELIGIBLE
    |
    v
PAYOUT_PENDING
    |
    v
COMPLETED
```

Additional branches should cover:

```
REJECTED
EXPIRED
PAYMENT_FAILED
PAYMENT_UNKNOWN
REVIEW_REQUIRED
DISPUTED
REFUND_PENDING
REFUNDED
PAYOUT_FAILED
```

Do not treat every failure as a terminal state. For example, `PAYMENT_UNKNOWN` means that Verifund needs to reconcile the provider state before deciding whether another payment attempt is safe.

## 8. Integrate Neon with LangGraph

Your Buyer Agent and Seller Agent use LangGraph to manage multi-step workflows.

LangGraph also needs persistence because your agents may pause for buyer approval, wait for a seller response, or resume after an interruption.

I recommend two separate persistence responsibilities.

Neon — Application database

Transactions, users, agents, mandates, offers, agreements, payments, evidence, and ledger records.

LangGraph PostgreSQL Checkpointer

Workflow checkpoints, graph state, pending interrupts, and resumable agent execution.

These can use the same Neon PostgreSQL project, but should use separate schemas or carefully isolated tables and database permissions.

For example:

```
Neon PostgreSQL
│
├── public
│   ├── users
│   ├── organizations
│   ├── shopping_missions
│   ├── offers
│   ├── agreements
│   ├── transactions
│   ├── payments
│   └── ledger_entries
│
├── agent_runtime
│   ├── checkpoints
│   ├── checkpoint_writes
│   └── workflow_state
│
└── system
    ├── audit_events
    └── webhook_events
```

The exact checkpoint table names depend on the checkpointer implementation and version.

### Example LangGraph integration

Install the PostgreSQL checkpointer:

```
uv add langgraph-checkpoint-postgres
```

Example:

```
from langgraph.checkpoint.postgres import PostgresSaverfrom app.config import settingswith PostgresSaver.from_conn_string(    settings.DATABASE_URL_UNPOOLED) as checkpointer:    checkpointer.setup()    graph = builder.compile(        checkpointer=checkpointer    )
```

For a production FastAPI service, initialize the checkpointer during application startup and manage its lifecycle rather than creating it for every request. Use the connection strategy recommended by the installed checkpointer version.

Each workflow should have a stable thread identifier:

```
config = {    "configurable": {        "thread_id": "transaction_VF-2048"    }}
```

This allows Verifund to resume a workflow associated with a transaction.

Important distinction: LangGraph checkpointing does not replace your application database. A checkpoint tells you where an agent workflow stopped; the transaction tables tell you what actually happened commercially and financially.

For example, the graph might be waiting for buyer approval, while the authoritative `buyer_approvals` table remains unchanged until the authenticated approval endpoint records the decision.

## 9. Use Neon with Redis Streams for event processing

Your architecture already uses Redis Streams for realtime communication and background event processing.

I would use the two systems together rather than trying to replace one with the other.

| Neon PostgreSQL               | Redis Streams                |
| ----------------------------- | ---------------------------- |
| Permanent transaction records | Event distribution           |
| Offers and agreements         | Agent progress notifications |
| Payment records               | Background job delivery      |
| Ledger entries                | Realtime status updates      |
| Audit history                 | Worker coordination          |
| Webhook deduplication records | Event consumption            |

Consider the following example:

PayPal sends a payment capture webhook.

The processing flow should be:

PayPal Webhook

Payment capture notification

FastAPI Webhook Handler

Validate webhook signature and event identity

Neon PostgreSQL

Persist event and update payment state atomically

Transactional Outbox

Record event to be published

Redis Streams

Distribute event to background workers

Verifund Workflow

Update transaction timeline and resume eligible workflows

I strongly recommend implementing the Transactional Outbox Pattern.

Why?

Imagine that your backend successfully updates Neon to `PAYMENT_CONFIRMED`, but Redis becomes unavailable before the event is published.

Without an outbox, the payment record is updated, but the downstream worker might never receive its notification.

With an outbox, both the payment update and the event record are committed in the same PostgreSQL transaction.

A background publisher can retry publishing the event until Redis confirms receipt.

For example:

```
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    tenant_id UUID,
    aggregate_id UUID NOT NULL,

    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,

    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Your workers should also be idempotent because Redis delivery and worker retries can produce duplicate processing attempts.

This gives Verifund a reliable event-processing foundation.

## 10. Database performance and indexing

As Verifund grows, you will have many transactions, offers, messages, and financial events.

You should create indexes around the queries your application performs most frequently.

For example:

```
CREATE INDEX idx_transactions_tenant
ON transactions(tenant_id);

CREATE INDEX idx_transactions_buyer
ON transactions(buyer_id, created_at DESC);

CREATE INDEX idx_transactions_seller
ON transactions(seller_id, created_at DESC);

CREATE INDEX idx_offers_negotiation
ON offers(negotiation_session_id, created_at DESC);

CREATE INDEX idx_payments_transaction
ON payments(transaction_id);

CREATE INDEX idx_evidence_transaction
ON fulfillment_evidence(transaction_id);

CREATE INDEX idx_webhook_provider_event
ON webhook_events(provider_event_id);
```

For webhook deduplication:

```
CREATE UNIQUE INDEX unique_provider_event
ON webhook_events(provider_event_id);
```

For preventing duplicate payout operations:

```
CREATE UNIQUE INDEX unique_transaction_payout
ON payouts(transaction_id, settlement_version);
```

The latter assumes one payout per transaction and settlement version. If you support multiple legitimate partial payouts, model payout sequence or allocation IDs instead.

Other recommendations:

- Use UUID primary keys.
- Use `TIMESTAMPTZ` for timestamps.
- Use `NUMERIC` or integer minor units for financial amounts.
- Use JSONB for flexible agent artifacts and structured metadata.
- Use foreign keys to enforce relationships.
- Paginate transaction history and negotiation messages.
- Avoid storing large binary files directly in PostgreSQL.

Financial integrity: For transfers, use atomic database transactions and enforce balanced accounting entries. An application-level `status` update alone is not a financial ledger.

## 11. Use Neon's database branching for development

[Practical Guide to Database Branching  - Neon](https://images.openai.com/static-rsc-4/9K41tb0VD7NsrP9DiPkPUvYw8-ULc02eMBAm9cTFuJGlcqkxYRchuAPt81I55tmLoQXf03luJG6IWRB2b95iWKd9OY2dboZLrSBxD9gujJMEMfs3q_mEnq0ib1QR2cVOpcRghIVDXVGx8CYto37eKoQgbrr_xP4u8t7FSnTJAso?purpose=inline)

[neon.com](https://neon.com/blog/practical-guide-to-database-branching?utm_source=chatgpt.com)

One of Neon's particularly useful capabilities is database branching.

You can create isolated database branches for development, testing, and production.

For Verifund, I recommend:

Production

Production

Real application environment, production records, restricted access.

Staging

Integration testing, PayPal Sandbox, migrations and release validation.

Development

Local development, mock transactions and agent experimentation.

Feature branches

Isolated schema and migration testing for individual features.

For example, when developing the negotiation system, you could create a branch to test changes to:

- `negotiation_sessions`
- `offers`
- `offer_versions`
- `agreements`

You can test your migrations without modifying production.

Neon's branching uses copy-on-write storage, making it useful for isolated development and testing workflows.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com&sz=32)

GitHub+1

See: [Neon database branching documentation](https://neon.com/docs/introduction/branching?utm_source=chatgpt.com).

## 12. Recommended Verifund backend project structure

I would organize your FastAPI backend around domain modules.

```
backend/
│
├── app/
│   ├── main.py
│   ├── config.py
│   │
│   ├── database/
│   │   ├── session.py
│   │   ├── base.py
│   │   ├── models/
│   │   └── repositories/
│   │
│   ├── domains/
│   │   ├── identity/
│   │   ├── organizations/
│   │   ├── marketplace/
│   │   ├── missions/
│   │   ├── agents/
│   │   ├── negotiations/
│   │   ├── agreements/
│   │   ├── transactions/
│   │   ├── approvals/
│   │   ├── payments/
│   │   ├── ledger/
│   │   ├── fulfillment/
│   │   ├── disputes/
│   │   └── audit/
│   │
│   ├── agents/
│   │   ├── buyer_agent/
│   │   └── seller_agent/
│   │
│   ├── a2a/
│   │   ├── client.py
│   │   ├── server.py
│   │   └── artifacts.py
│   │
│   ├── integrations/
│   │   ├── paypal/
│   │   ├── channel3/
│   │   ├── messaging/
│   │   └── storage/
│   │
│   ├── workflows/
│   │   ├── transaction_graph.py
│   │   ├── negotiation_graph.py
│   │   └── fulfillment_graph.py
│   │
│   ├── events/
│   │   ├── publisher.py
│   │   ├── consumer.py
│   │   └── outbox.py
│   │
│   └── workers/
│       ├── webhook_worker.py
│       ├── payout_worker.py
│       └── reconciliation_worker.py
│
├── migrations/
├── tests/
├── alembic.ini
├── pyproject.toml
└── .env
```

Each domain should own its models, schemas, repositories, and business operations.

For example:

- `payments/` owns payment records and payment-state transitions.
- `agreements/` owns agreement versioning and validation.
- `ledger/` owns accounting entries.
- `transactions/` coordinates the overall transaction lifecycle.

This prevents your agents from directly manipulating critical financial records.

## 13. Security and reliability considerations

Because Verifund handles payment-related information and buyer/seller agreements, I would prioritize these controls:

| Area                 | Recommended implementation                     |
| -------------------- | ---------------------------------------------- |
| Database credentials | Separate application and migration roles       |
| Tenant isolation     | PostgreSQL RLS and backend authorization       |
| Payment security     | Never store card numbers or CVVs               |
| Financial integrity  | Atomic transactions and append-only ledger     |
| Webhooks             | Signature verification and event deduplication |
| Agent permissions    | Mandate-based authorization                    |
| Database migrations  | Alembic and version-controlled migrations      |
| File security        | Private object storage and signed URLs         |
| Recovery             | Reconciliation workers                         |
| Auditability         | Immutable audit events and agreement versions  |

One additional consideration: don't allow the LLM to directly update payment states.

Instead, it should request an operation through a controlled backend service.

For example:

```
Buyer Agent
    |
    v
Request payment operation
    |
    v
Verifund Payment Service
    |
    v
Validate:
- Buyer approval
- Agreement version
- Transaction status
- Payment eligibility
    |
    v
PayPal API
    |
    v
Verify provider response
    |
    v
Persist result in Neon
```

This preserves the separation between agent reasoning, transaction authorization, and financial execution.

## 14. My recommended implementation strategy

I would build Neon integration in five phases.

| Phase | Implementation                                         | Expected outcome                  |
| ----- | ------------------------------------------------------ | --------------------------------- |
| 1     | Neon setup, SQLAlchemy, Alembic, tenant model          | Working database foundation       |
| 2     | Marketplace, agents, missions, A2A and offers          | Persistent agentic commerce       |
| 3     | Agreements, transactions and approvals                 | Reliable transaction coordination |
| 4     | PayPal, ledger, webhooks and reconciliation            | Financial recordkeeping           |
| 5     | Fulfillment, disputes, audit and LangGraph persistence | Complete transaction lifecycle    |

Don't start by implementing all the tables simultaneously.

Start with the transaction foundation and build one working vertical slice before expanding.

### Useful Neon documentation

- [Connecting Neon to your application](https://neon.com/docs/get-started/connect-neon?utm_source=chatgpt.com)
- [Connection pooling](https://neon.com/docs/connect/connection-pooling?utm_source=chatgpt.com)
- [SQLAlchemy integration](https://neon.com/docs/guides/sqlalchemy?utm_source=chatgpt.com)
- [Database branching](https://neon.com/docs/introduction/branching?utm_source=chatgpt.com)
- [Row-Level Security](https://neon.com/docs/guides/rls?utm_source=chatgpt.com)

## 15. Final architectural recommendation

Recommended

&#x20;Use Neon PostgreSQL as Verifund's central relational database, with SQLAlchemy and Alembic in FastAPI.

The resulting architecture should look like this:

| Component              | Technology                        | Responsibility                                    |
| ---------------------- | --------------------------------- | ------------------------------------------------- |
| Frontend               | Next.js 16                        | User interfaces                                   |
| Backend                | FastAPI                           | Application and transaction APIs                  |
| Relational database    | Neon PostgreSQL                   | Authoritative application and transaction records |
| ORM                    | SQLAlchemy                        | Database access                                   |
| Migrations             | Alembic                           | Schema versioning                                 |
| Agent orchestration    | LangGraph                         | Stateful agent workflows                          |
| Agent communication    | A2A                               | Buyer/seller agent interoperability               |
| Checkpoint persistence | LangGraph PostgreSQL checkpointer | Workflow recovery                                 |
| Event infrastructure   | Redis Streams                     | Background event delivery                         |
| Payment processing     | PayPal                            | Payment operations                                |
| File storage           | S3-compatible object storage      | Evidence and documents                            |

The distinction I would preserve throughout development is:

- Neon knows what Verifund has recorded and authorized.
- LangGraph knows where an agent workflow is and how to resume it.
- Redis distributes events between services.
- PayPal confirms what actually happened to the money.

Your PostgreSQL data model should reflect this separation.&#x20;

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt

The next implementation step I recommend is building the complete SQLAlchemy models and Alembic migrations for Verifund's multi-tenant database, starting with organizations, users, agents, shopping missions, A2A negotiations, agreements, transactions, and payments.
