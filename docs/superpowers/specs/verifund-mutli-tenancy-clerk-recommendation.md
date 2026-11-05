# Implementing Multi-Tenancy in Verifund with Clerk

For Verifund, I recommend using Clerk for authentication, user management, and organization membership, while implementing tenant isolation, agent ownership, transaction authorization, and financial permissions in your FastAPI backend and PostgreSQL database.

The important architectural decision is not to make Clerk responsible for your entire multi-tenant system. Clerk should manage who the user is, which organization they belong to, and their organization-level membership and roles. Verifund should control what that organization and its agents can access and do.

This approach fits the architecture we've discussed: buyers and sellers operate under separate tenants, each tenant can own multiple agents, and Buyer Agents and Seller Agents communicate across tenant boundaries through the Verifund Orchestrator.

## 1. Overall architecture

I would divide multi-tenancy into five layers:

1. Clerk: User authentication, organization creation, membership, invitations, and organization roles.
2. Verifund Tenancy Service: Maps Clerk organizations to Verifund tenants and resolves tenant context.
3. PostgreSQL: Stores tenant-owned resources and enforces data isolation.
4. Agent Tenancy and Authorization: Controls agent ownership, credentials, capabilities, and execution permissions.
5. Transaction and A2A Authorization: Allows authorized interactions between buyer and seller tenants without exposing private tenant data.

Next.js 16 Frontend

Buyer Portal · Seller Portal · Admin Workspace

Clerk

Authentication · Users · Organizations · Memberships · Roles

FastAPI Backend

JWT verification · Tenant resolution · Authorization · Business logic

Tenancy Service

Tenant context and memberships

Agent Authorization

Agent identity and policies

Transaction Service

Buyer and seller participants

A2A Orchestrator

Mediated agent communication

PostgreSQL + Row-Level Security

Tenant-owned data · Transaction participants · Audit records

The frontend uses Clerk to authenticate the user. FastAPI independently verifies the user's Clerk-issued token and resolves the corresponding Verifund tenant before accessing protected resources.

Do not rely on frontend organization selection as authorization. The backend must verify every request.

## 2. Model the relationship between Clerk Organizations and Verifund Tenants

This is the most important modeling decision.

Clerk provides Organizations as a way to group users, manage memberships, and apply organization roles and permissions.

Verifund should map each Clerk Organization to an internal tenant.

For example:

Clerk Organization

Acme Technologies

org_acme_clerk

Mapped to Verifund tenant

Verifund Tenant

Acme Technologies

tenant_acme

Members

- Organization Owner
- Administrator
- Buyer
- Finance Manager

  Resources

- Buyer Agents
- Shopping mandates
- Transactions
- Agreements
- Payment configuration

A seller organization would have its own Clerk Organization and corresponding Verifund tenant.

Clerk Organization

TechSupply

org_techsupply_clerk

Verifund Tenant

TechSupply

tenant_techsupply

Resources

- Seller Agents
- Product catalog
- Inventory
- Pricing policies
- Seller integrations
- Fulfillment records

The mapping should be stored in your own database. Do not use the Clerk Organization ID as the only tenant identifier throughout your business domain.

### Recommended tenant types

Verifund should initially support:

| Tenant type    | Purpose                               |
| -------------- | ------------------------------------- |
| `INDIVIDUAL`   | Individual buyer or seller            |
| `ORGANIZATION` | Business, merchant, or enterprise     |
| `MARKETPLACE`  | Marketplace operating within Verifund |

A Clerk Organization can represent an organization tenant. For individual users, create an internal individual tenant or personal workspace according to your product model. Not every individual account needs to become a Clerk Organization.

Important: A person can belong to multiple organizations. Their active organization is a request context, not their permanent identity.

## 3. Configure Clerk Organizations, roles, and permissions

Enable Organizations in your Clerk application.

In the Clerk Dashboard:

1. Open your Clerk application.
2. Enable Organizations.
3. Configure organization creation and membership requirements.
4. Configure your default and custom roles.
5. Configure invitations and organization switching.
6. Set the organization creator role.

Clerk provides an `OrganizationSwitcher` component for creating, switching, and managing organizations. It also supports organization memberships, invitations, custom roles, and permissions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

Clerk Docs+1

### Recommended Verifund roles

I would start with the following roles:

| Clerk organization role | Verifund responsibility                            |
| ----------------------- | -------------------------------------------------- |
| `org:admin`             | Organization administration                        |
| `org:buyer`             | Buyer operations                                   |
| `org:seller`            | Seller operations                                  |
| `org:finance`           | Financial records and permitted payment operations |
| `org:reviewer`          | Agreement and transaction review                   |
| `org:viewer`            | Read-only access                                   |

You can also introduce an `org:owner` role if your business rules distinguish ownership from administration.

For example, a seller organization could have:

```
TechSupply
│
├── Bonnie — Owner
│
├── Alex — Admin
│
├── David — Seller
│
├── Mary — Finance
│
└── John — Viewer
```

A buyer organization might have:

```
Acme Technologies
│
├── Owner
│
├── Procurement Manager
│
├── Buyer
│
└── Finance Manager
```

Clerk roles should manage membership-level access. Verifund should implement additional domain-specific permissions for agents, agreements, transactions, and financial operations.

### Important Clerk permission detail

Clerk distinguishes system permissions from custom permissions. Its documentation notes that system permissions are not included in session claims, so use custom permissions when you need permission checks based on the session token. Custom organization roles and permissions also have production plan considerations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

Clerk Docs+1

I would avoid putting every Verifund business permission into Clerk. Use Clerk for organization-level permissions and keep the more granular authorization model in your backend.

For example:

| Permission                      | Authorization owner |
| ------------------------------- | ------------------- |
| Invite organization members     | Clerk               |
| Change member role              | Clerk               |
| Manage organization profile     | Clerk               |
| Create Seller Agent             | Verifund            |
| Change agent negotiation limits | Verifund            |
| Access private inventory        | Verifund            |
| Accept an agreement             | Verifund            |
| Authorize payment               | Verifund            |
| Release settlement              | Verifund            |

This avoids coupling your financial authorization model to an identity-provider role configuration.

## 4. Design the Verifund database

Clerk stores user and organization identity information. PostgreSQL stores Verifund's application data and the relationships between tenants, users, agents, transactions, and agreements.

I recommend using internal UUIDs for tenant and user records while retaining Clerk IDs as unique external identifiers.

### A. Core identity and tenancy tables

```
CREATE TABLE users (
    id UUID PRIMARY KEY,
    clerk_user_id TEXT UNIQUE NOT NULL,
    email TEXT,
    full_name TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tenants (
    id UUID PRIMARY KEY,
    clerk_org_id TEXT UNIQUE,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    tenant_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tenant_memberships (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    clerk_membership_id TEXT,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (tenant_id, user_id)
);
```

The `clerk_org_id` is the mapping between a Clerk Organization and a Verifund tenant.

The `clerk_user_id` maps a Clerk user to an internal Verifund user.

For individual tenants, `clerk_org_id` can be nullable. You should enforce the tenant-type-specific mapping rules in your application and database constraints.

### B. Tenant-owned agents

Extend the agent model we've already discussed:

```
CREATE TABLE agents (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CONFIGURING',
    agent_card_url TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (tenant_id, id)
);

CREATE TABLE agent_credentials (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    agent_id UUID NOT NULL,
    credential_reference TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,

    FOREIGN KEY (tenant_id, agent_id)
        REFERENCES agents(tenant_id, id)
);
```

The tenant owns the agent, but the agent has its own machine identity and credentials.

For example:

```
Acme Tenant
    ├── Buyer Agent 001
    ├── Buyer Agent 002
    └── Procurement Agent

TechSupply Tenant
    ├── Seller Agent 001
    └── Seller Agent 002
```

A user who manages these agents does not automatically become the agent's runtime identity. Keep human authentication and machine authentication separate.

### C. Shared transactions between tenants

This is where Verifund's data model differs from a conventional SaaS application.

A transaction is not owned by just one tenant. It involves at least two parties.

I recommend:

```
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    buyer_tenant_id UUID NOT NULL REFERENCES tenants(id),
    seller_tenant_id UUID NOT NULL REFERENCES tenants(id),
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE transaction_participants (
    id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL REFERENCES transactions(id),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    participant_type TEXT NOT NULL,
    permissions JSONB NOT NULL DEFAULT '{}',
    joined_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (transaction_id, tenant_id)
);
```

For example:

| Resource                      | Acme buyer tenant              | TechSupply seller tenant       |
| ----------------------------- | ------------------------------ | ------------------------------ |
| Buyer's mandate               | Private                        | No access                      |
| Seller's inventory            | No access                      | Private                        |
| Negotiated offer              | Authorized access              | Authorized access              |
| Agreement                     | Authorized access              | Authorized access              |
| Fulfillment evidence          | Authorized access as permitted | Authorized access as permitted |
| Internal seller pricing rules | No access                      | Private                        |

This participant-based model is essential because a buyer and seller must share a transaction without gaining unrestricted access to each other's organization data.

## 5. Implement authentication in Next.js with Clerk

Install Clerk's Next.js SDK:

```
npm install @clerk/nextjs
```

Configure your environment:

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
```

Add the Clerk provider to your application.

```
// app/layout.tsx

import {
  ClerkProvider,
} from "@clerk/nextjs";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>{children}</body>
      </html>
    </ClerkProvider>
  );
}
```

Add the organization switcher to your authenticated dashboard:

```
// components/organization-switcher.tsx

"use client";

import {
  OrganizationSwitcher,
  UserButton,
} from "@clerk/nextjs";

export function OrganizationControls() {
  return (
    <div className="flex items-center gap-4">
      <OrganizationSwitcher
        afterCreateOrganizationUrl="/onboarding"
        afterSelectOrganizationUrl="/dashboard"
      />

      <UserButton />
    </div>
  );
}
```

The switcher lets a user move between organizations they belong to. You can place it in the main Verifund application header.

For example, someone who works with two companies could switch between Acme Technologies and another organization without creating a second Clerk user account.

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

Clerk Docs+1

### Add organization context to API requests

Your Next.js frontend must obtain the token for the active organization and send it to FastAPI.

```
"use client";

import { useAuth } from "@clerk/nextjs";

export function useVerifundApi() {
  const { getToken } = useAuth();

  async function request(
    path: string,
    options: RequestInit = {}
  ) {
    const token = await getToken();

    return fetch(
      `${process.env.NEXT_PUBLIC_API_URL}${path}`,
      {
        ...options,
        headers: {
          ...options.headers,
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      }
    );
  }

  return { request };
}
```

For multi-tab applications, explicitly obtain the active organization token for each request rather than relying on a potentially stale shared session cookie. Clerk documents that different tabs can maintain different active organization contexts.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

Clerk Docs

## 6. Verify Clerk session tokens in FastAPI

Your Python backend must independently authenticate every user request.

For Verifund, I recommend Clerk's official Python package, `clerk-backend-api`, rather than writing JWT verification yourself. It provides `authenticate_request()` for verifying Clerk session tokens in FastAPI.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

clerk.com+1

Install it:

```
uv add clerk-backend-api
```

Configure your backend environment:

```
CLERK_SECRET_KEY=sk_test_...
CLERK_JWT_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
CLERK_AUTHORIZED_PARTIES=http://localhost:3000
```

- `CLERK_SECRET_KEY` authorizes backend API operations.
- `CLERK_JWT_KEY` verifies signed session tokens.
- `CLERK_AUTHORIZED_PARTIES` restricts which frontend origins can present the tokens.

Keep the secret key on the backend. The public JWT verification key is not a replacement for the secret key.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

clerk.com+1

### A. Create the authentication dependency

```
# app/auth/clerk.pyimport osfrom fastapi import HTTPException, Requestfrom clerk_backend_api import (    authenticate_request,    AuthenticateRequestOptions,)def require_clerk_user(request: Request) -> dict:    state = authenticate_request(        request,        AuthenticateRequestOptions(            secret_key=os.environ["CLERK_SECRET_KEY"],            jwt_key=os.environ["CLERK_JWT_KEY"],            authorized_parties=os.environ[                "CLERK_AUTHORIZED_PARTIES"            ].split(","),            accepts_token=["session_token"],        ),    )    if not state.is_signed_in:        raise HTTPException(            status_code=401,            detail="Authentication required",        )    payload = state.payload    return {        "clerk_user_id": payload["sub"],        "clerk_org_id": payload.get("org_id"),        "clerk_org_role": payload.get("org_role"),
```

The important claims are:

| Claim             | Purpose                                   |
| ----------------- | ----------------------------------------- |
| `sub`             | Clerk user ID                             |
| `org_id`          | Active Clerk Organization ID              |
| `org_role`        | User's organization role                  |
| `org_permissions` | Available custom organization permissions |

The current Clerk Python SDK enriches the decoded session payload with organization fields such as `org_id`, `org_role`, and `org_permissions`.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

clerk.com

### B. Build the tenant context dependency

Authentication only establishes who the user is. The next step is resolving their Verifund tenant.

```
# app/tenancy/context.pyfrom dataclasses import dataclassfrom uuid import UUID@dataclass(frozen=True)class TenantContext:    user_id: UUID    tenant_id: UUID    clerk_user_id: str    clerk_org_id: str    role: str
```

Then create a dependency that maps the authenticated Clerk identity to your internal database records.

```
# app/tenancy/dependencies.pyfrom fastapi import Depends, HTTPExceptionfrom app.auth.clerk import require_clerk_userfrom app.tenancy.context import TenantContextfrom app.db.repositories import (    get_user_by_clerk_id,    get_tenant_by_clerk_org_id,    get_active_membership,)async def get_tenant_context(    identity: dict = Depends(require_clerk_user),) -> TenantContext:    clerk_org_id = identity.get("clerk_org_id")    if not clerk_org_id:        raise HTTPException(            status_code=403,            detail="An active organization is required",        )    user = await get_user_by_clerk_id(        identity["clerk_user_id"]    )    if not user:        raise HTTPException(404, "User not provisioned")    tenant = await get_tenant_by_clerk_org_id(        clerk_org_id    )
```

This creates a crucial security boundary:

```
Clerk Session
     |
     v
Verify JWT
     |
     v
Read Clerk User ID + Active Organization ID
     |
     v
Resolve Internal User
     |
     v
Resolve Verifund Tenant
     |
     v
Verify Tenant Membership
     |
     v
Create TenantContext
     |
     v
Execute Authorized Request
```

The backend should not accept a `tenant_id` from the frontend as proof of tenant access. The active Clerk organization is a useful context selector, but the database membership and authorization checks determine whether access is permitted.

### C. Protect FastAPI endpoints

```
# app/routers/agents.pyfrom fastapi import APIRouter, Dependsfrom app.tenancy.context import TenantContextfrom app.tenancy.dependencies import get_tenant_contextrouter = APIRouter(prefix="/agents")@router.get("/")async def list_agents(    context: TenantContext = Depends(        get_tenant_context    ),):    return await agent_service.list_by_tenant(        tenant_id=context.tenant_id    )
```

When Acme requests its agents, the backend retrieves only Acme's agents. When TechSupply makes the same request, it retrieves only TechSupply's agents.

The tenant context should be passed explicitly through service and repository layers rather than being inferred from arbitrary request data.

## 7. Synchronize Clerk data with Verifund

You need a reliable way to keep your internal database synchronized with Clerk.

I recommend using two mechanisms:

- Synchronous provisioning: Create the Verifund tenant and its initial records as part of your organization onboarding workflow.
- Clerk webhooks: Synchronize subsequent identity and membership changes.

This is important because Clerk webhooks are asynchronous. They are useful for keeping records synchronized, but you should not depend on a webhook arriving immediately to complete a critical onboarding request.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

Clerk Docs+1

### Recommended events

| Clerk event                      | Verifund action                                       |
| -------------------------------- | ----------------------------------------------------- |
| `user.created`                   | Create internal user                                  |
| `user.updated`                   | Update user profile                                   |
| `user.deleted`                   | Deactivate or anonymize according to retention policy |
| `organization.created`           | Create or reconcile tenant                            |
| `organization.updated`           | Update tenant profile                                 |
| `organization.deleted`           | Suspend tenant and initiate lifecycle handling        |
| `organizationMembership.created` | Create tenant membership                              |
| `organizationMembership.updated` | Synchronize role                                      |
| `organizationMembership.deleted` | Revoke membership                                     |

### Organization creation workflow

For example, when a seller registers TechSupply:

```
Seller signs up with Clerk
          |
          v
Creates TechSupply Organization
          |
          v
Next.js onboarding calls FastAPI
          |
          v
FastAPI verifies Clerk session
          |
          v
Verifund creates internal tenant
          |
          v
Stores Clerk Organization ID mapping
          |
          v
Creates seller profile
          |
          v
Starts seller onboarding
          |
          v
Seller configures commerce integrations
          |
          v
Verifund provisions Seller Agent
```

Make provisioning idempotent. If the request is retried, it must not create duplicate tenants or agent identities.

For webhooks, verify the webhook signature, store the event ID, and make event processing idempotent. A webhook retry must not create duplicate memberships or overwrite newer state with stale information.

## 8. Enforce tenant isolation with PostgreSQL Row-Level Security

Clerk authenticates users and identifies their organization. PostgreSQL must enforce data isolation even if an application endpoint accidentally omits a tenant filter.

For Verifund, I recommend:

Shared PostgreSQL database + shared schema + tenant-scoped records + Row-Level Security (RLS).

This is a good starting point for a multi-tenant marketplace because you can support many buyers and sellers without deploying a separate database for every organization.

### A. Enable RLS on tenant-owned tables

For example, consider the `agents` table.

```
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;

ALTER TABLE agents FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_agents_isolation
ON agents
USING (
    tenant_id =
    NULLIF(
        current_setting('app.tenant_id', true),
        ''
    )::uuid
)
WITH CHECK (
    tenant_id =
    NULLIF(
        current_setting('app.tenant_id', true),
        ''
    )::uuid
);
```

This ensures that a database query can only access agent records belonging to the current tenant context.

Apply similar policies to:

- Seller profiles.
- Buyer profiles.
- Catalogs.
- Inventory.
- Seller pricing policies.
- Agent configurations.
- Agent credentials.
- Agent execution records.
- Private integrations.
- Tenant-specific documents and memory.

### B. Set tenant context for each database transaction

After FastAPI authenticates the user and resolves the tenant, set the tenant ID inside the database transaction.

For example:

```
# app/db/tenant_session.pyfrom sqlalchemy import textasync def set_database_tenant(    session,    tenant_id: str,):    await session.execute(        text(            "SELECT set_config("            "'app.tenant_id', :tenant_id, true)"        ),        {"tenant_id": tenant_id},    )
```

Then:

```
async with session.begin():    await set_database_tenant(        session,        str(context.tenant_id),    )    agents = await agent_repository.list_agents(        session    )
```

The third argument to `set_config` makes the setting transaction-local. This matters when using connection pooling: tenant context must not leak between requests.

Use a non-superuser application database role without `BYPASSRLS`. RLS is a defense-in-depth layer, not a replacement for application-level authorization.

### C. Handle cross-tenant transactions separately

There is an important exception to ordinary tenant isolation.

Suppose Acme purchases a laptop from TechSupply.

Both tenants need access to certain transaction records, but neither should gain unrestricted access to the other's private data.

Therefore, don't use a simple `tenant_id` RLS policy for every table.

Use participant-aware authorization for shared resources.

For example:

```
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY transaction_participant_access
ON transactions
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM transaction_participants tp
        WHERE tp.transaction_id = transactions.id
          AND tp.tenant_id =
              NULLIF(
                  current_setting('app.tenant_id', true),
                  ''
              )::uuid
    )
);
```

This is an illustrative policy. In production, ensure the participant lookup itself has a safe security design—for example, a carefully controlled security-definer authorization function or a policy arrangement that avoids recursive RLS problems.

Also implement separate policies for inserting and updating transactions. A tenant should not be able to add itself to another transaction or modify a transaction merely because it knows the transaction ID.

The same participant-aware access model should apply to agreements, evidence, and other shared transaction resources.

## 9. Integrate Clerk with Buyer and Seller Agent tenancy

This is particularly important for Verifund because the application contains both human users and autonomous agents.

Clerk authenticates human users. Verifund manages autonomous agent identities.

Do not use Clerk user session tokens as Seller Agent or Buyer Agent credentials.

Your identity model should look like this:

Human identity

Clerk User

Authentication, MFA, user session

Verifund Tenant

Organization membership and authorization

Buyer Agent

Buyer mandate and tools

Seller Agent

Seller catalog and policies

Verifund Agent Identity Service

Machine identities · Credentials · Policies · Execution contexts

For example:

- Acme's Clerk Organization owns the Acme tenant.
- Acme's tenant owns Buyer Agent 001.
- TechSupply's Clerk Organization owns the TechSupply tenant.
- TechSupply's tenant owns Seller Agent 001.
- Both agents participate in a shared transaction.

### Effective agent permissions

Keep the three policy levels we discussed:

\\[ P\_{\text{effective}} = P\_{\text{tenant}} \cap P\_{\text{agent}} \cap P\_{\text{run}} \\]

For example:

| Permission         | Buyer Agent                    | Seller Agent                  |
| ------------------ | ------------------------------ | ----------------------------- |
| Product discovery  | Yes                            | Yes, own catalog              |
| Inventory access   | Public/authorized availability | Own inventory                 |
| Negotiate offers   | Yes                            | Yes                           |
| Create offers      | No                             | Yes                           |
| Propose agreements | Yes                            | Yes                           |
| Accept agreements  | Only with delegated authority  | Only with delegated authority |
| Authorize payment  | Restricted                     | Restricted                    |
| Release settlement | No                             | No                            |

The backend must enforce these restrictions even if an agent's LLM instructions tell it to perform a prohibited action.

## 10. Preserve the existing mediated A2A architecture

Clerk should not be inserted into every Buyer Agent-to-Seller Agent communication as if agents were ordinary browser users.

Instead, use Verifund's existing Orchestrator and machine identity system.

Consider this example:

```
Acme Clerk Organization
          |
          v
Acme Verifund Tenant
          |
          v
Acme Buyer Agent
          |
          v
Verifund Orchestrator
          |
          +--> Verify buyer agent identity
          |
          +--> Verify buyer tenant ownership
          |
          +--> Resolve seller from Registry
          |
          +--> Resolve seller credentials
          |
          +--> Validate transaction permissions
          |
          v
TechSupply Seller Agent
          |
          v
Authenticated A2A Response
          |
          v
Verifund Orchestrator
          |
          v
Resume Buyer Agent Graph
```

The Orchestrator should construct an internal trusted context:

```
@dataclass(frozen=True)class AgentCallContext:    transaction_id: str    buyer_tenant_id: str    seller_tenant_id: str    buyer_agent_id: str    seller_agent_id: str    buyer_run_id: str    request_id: str    correlation_id: str
```

Before sending the request, validate:

1. The Buyer Agent is active and belongs to the buyer tenant.
2. The Seller Agent is active and belongs to the seller tenant.
3. Both agents are authorized participants in the transaction.
4. The requested operation is permitted by both agents' policies.
5. The transaction is in a state that allows the operation.

Keep seller bearer tokens outside LangGraph state, traces, logs, and AG-UI. Retrieve credentials from the trusted credential service when the Orchestrator makes the call.

This ensures that Clerk organization membership, tenant ownership, agent identity, and A2A authorization remain separate security boundaries.

## 11. Handle individual users and organizations

Verifund may eventually support both individual buyers and business sellers.

I would implement the following onboarding model:

| Account type         | Clerk identity            | Verifund tenant     |
| -------------------- | ------------------------- | ------------------- |
| Individual buyer     | Clerk User                | Individual tenant   |
| Individual seller    | Clerk User                | Individual tenant   |
| Business buyer       | Clerk User + Organization | Organization tenant |
| Business seller      | Clerk User + Organization | Organization tenant |
| Marketplace operator | Clerk User + Organization | Marketplace tenant  |

For individual accounts, you can create an internal personal tenant associated with the Clerk user ID without forcing every user to create a Clerk Organization.

When an individual creates or joins a business organization, the user can then operate within that organization's active context.

A person may therefore have:

```
Clerk User: user_123
    |
    +── Personal Tenant
    |
    +── Acme Organization
    |
    +── Other Business Organization
```

The user switches context in the frontend, and FastAPI resolves the correct tenant for each request.

## 12. Extend tenant isolation beyond PostgreSQL

A common mistake is implementing RLS in PostgreSQL but forgetting that Verifund also has agent memory, LangGraph checkpoints, queues, and object storage.

You need tenant isolation across the entire application.

| Component             | Isolation strategy                           |
| --------------------- | -------------------------------------------- |
| PostgreSQL            | RLS and tenant-scoped queries                |
| Redis                 | Tenant-prefixed keys                         |
| LangGraph checkpoints | Tenant-scoped thread IDs                     |
| Agent memory          | Tenant and agent scoped                      |
| Object storage        | Tenant-specific prefixes and access policies |
| SSE connections       | Tenant and membership authorization          |
| Event queues          | Tenant identifiers and authorization checks  |
| Logs and traces       | Tenant and run identifiers; redact secrets   |
| Agent credentials     | Tenant-owned secret references               |
| Commerce integrations | Tenant-specific credentials and scopes       |

For example, a LangGraph checkpoint identifier could be:

```
thread_id = f"{tenant_id}:{run_id}"
```

However, the thread ID is not an authorization mechanism. Every graph resume must authenticate the caller and validate access to the associated run.

Likewise, an SSE client must not be allowed to subscribe to another tenant's transaction events by guessing a transaction ID.

## 13. Clerk webhooks and lifecycle management

Clerk should remain the identity source of truth for users and organization memberships. Verifund should remain the source of truth for business records, agents, transactions, agreements, and financial state.

I would establish these lifecycle rules:

| Clerk change                      | Verifund response                                |
| --------------------------------- | ------------------------------------------------ |
| User invited                      | Create or update pending membership              |
| User joins organization           | Activate membership                              |
| User role changes                 | Synchronize membership role                      |
| User leaves organization          | Revoke tenant access                             |
| Organization suspended internally | Block tenant operations                          |
| Organization deleted              | Apply controlled archival and retention workflow |

Do not automatically delete a Verifund tenant when a Clerk Organization is deleted. The tenant may have financial records, agreements, evidence, disputes, and audit history that must be retained.

Similarly, suspending an organization should block new operations while preserving existing transaction records and allowing whatever restricted dispute or compliance actions are required.

## 14. Recommended Verifund backend structure

I would organize your FastAPI project as follows:

```
backend/app/
│
├── auth/
│   ├── clerk.py
│   ├── dependencies.py
│   └── webhooks.py
│
├── tenancy/
│   ├── models.py
│   ├── schemas.py
│   ├── context.py
│   ├── dependencies.py
│   ├── middleware.py
│   ├── service.py
│   ├── permissions.py
│   └── repository.py
│
├── users/
│   ├── models.py
│   ├── service.py
│   └── repository.py
│
├── organizations/
│   ├── models.py
│   ├── service.py
│   └── invitations.py
│
├── agent_tenancy/
│   ├── models.py
│   ├── provisioning.py
│   ├── identity.py
│   ├── credentials.py
│   ├── policies.py
│   ├── authorization.py
│   └── lifecycle.py
│
├── registry/
│   ├── agent_cards.py
│   ├── discovery.py
│   └── registration.py
│
├── orchestrator/
│   ├── graph.py
│   ├── a2a_mediation.py
│   └── run_manager.py
│
├── transactions/
│   ├── models.py
│   ├── participants.py
│   └── service.py
│
├── agreements/
├── payments/
├── fulfillment/
├── settlement/
├── audit/
└── db/
    ├── session.py
    ├── tenant_session.py
    └── rls.py
```

## 15. Implementation roadmap

I would implement this in the following order:

| Phase | What to implement                             | Result                                               |
| ----- | --------------------------------------------- | ---------------------------------------------------- |
| 1     | Clerk authentication and Next.js integration  | Users can sign in                                    |
| 2     | Clerk Organizations                           | Users can create, join, and switch organizations     |
| 3     | Internal users, tenants, and memberships      | Clerk identities map to Verifund                     |
| 4     | FastAPI token verification                    | Backend authenticates users                          |
| 5     | Tenant context and authorization              | Requests operate within authorized tenants           |
| 6     | PostgreSQL RLS                                | Database enforces isolation                          |
| 7     | Tenant-owned Buyer and Seller Agents          | Agents belong to organizations                       |
| 8     | Agent credentials and policy enforcement      | Secure machine identities                            |
| 9     | Participant-aware transactions and agreements | Buyer and seller tenants share authorized records    |
| 10    | A2A mediation and tenant-scoped execution     | Agents communicate securely                          |
| 11    | Tenant-aware infrastructure                   | Redis, memory, SSE, storage, and events are isolated |
| 12    | Security and isolation testing                | Cross-tenant access is prevented                     |

### Essential security tests

Before production, explicitly test these scenarios:

- Acme cannot retrieve TechSupply's private inventory.
- Acme cannot retrieve TechSupply's Seller Agent credentials.
- A user cannot access an organization they are not a member of.
- A user removed from an organization loses access.
- Switching Clerk organizations changes the backend tenant context.
- A Buyer Agent cannot access another buyer's private mandate.
- A Seller Agent cannot access another seller's pricing policies.
- Both parties can access only the transaction resources authorized for them.
- A user cannot change `tenant_id` in a request to bypass tenant isolation.
- A suspended agent cannot initiate new A2A operations.
- A revoked user or agent cannot resume an unauthorized execution.

## 16. Final architecture recommendation

## Verifund multi-tenancy responsibility matrix

| Layer                   | Technology              | Responsibility                          |
| ----------------------- | ----------------------- | --------------------------------------- |
| Authentication          | Clerk                   | User identity and sessions              |
| Organization management | Clerk Organizations     | Membership and roles                    |
| Tenant management       | FastAPI                 | Internal tenant lifecycle               |
| Authorization           | Verifund Policy Service | Business permissions                    |
| Data isolation          | PostgreSQL RLS          | Tenant data boundaries                  |
| Agent identity          | Verifund Agent Service  | Buyer/Seller Agent identities           |
| Agent discovery         | MarketMesh Registry     | Agent Cards and discovery               |
| Agent communication     | A2A + Orchestrator      | Cross-tenant agent requests             |
| Workflow execution      | LangGraph               | Tenant-scoped agent runs                |
| Payments                | PayPal integration      | Payment operations and reconciliation   |
| Audit                   | Verifund Audit Service  | Traceable security and financial events |

My strongest recommendation: Use Clerk Organizations as the external identity and organization-management layer, but make Verifund's internal tenant model the foundation of your application authorization.

In particular, do not make a Clerk `org_id` the only security boundary. Resolve it to an internal tenant, verify membership, apply business permissions, and enforce database isolation. Treat Buyer and Seller Agents as separate tenant-owned machine identities. Treat shared transactions as participant-authorized resources.

This gives Verifund a coherent architecture for individual buyers, business buyers, sellers, marketplaces, and multiple autonomous agents per organization.

### Useful Clerk documentation

- [Clerk Organizations — multi-tenant applications](https://clerk.com/docs/guides/organizations/overview?utm_source=chatgpt.com)
- [Clerk Organizations with Next.js](https://clerk.com/docs/guides/organizations/getting-started?utm_source=chatgpt.com)
- [Organization roles and permissions](https://clerk.com/docs/guides/organizations/control-access/roles-and-permissions?utm_source=chatgpt.com)
- [Clerk authentication with a Python backend](https://clerk.com/articles/how-to-add-authentication-to-a-python-backend?utm_source=chatgpt.com)
- [Clerk webhooks](https://clerk.com/docs/guides/development/webhooks/overview?utm_source=chatgpt.com)

The next practical step is to implement Phase 1–6 as one foundation: Clerk setup, organization onboarding, FastAPI authentication, tenant resolution, SQLAlchemy models, and PostgreSQL RLS. That will give the Buyer Agent and Seller Agent services a secure tenancy layer to build on.
