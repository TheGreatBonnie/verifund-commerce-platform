# Configuring an A2A Seller Agent during Verifund seller onboarding

> **Superseded 2026-11-06** — This recommendation is superseded by
> `docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md`
> (Appendix B), per the 2026-11-06 onboarding grill. Do not implement from
> this file. Kept for provenance only.

The seller should configure its A2A Seller Agent after the business has authenticated through Clerk and its organization context has been established.

The key design principle is that Clerk authenticates the human seller administrator, while Verifund provisions and manages a separate machine identity for the Seller Agent.

These are two different identities:

- Human identity: The seller administrator signs in through Clerk and manages the seller organization.
- Agent identity: The Seller Agent receives its own Verifund agent ID, A2A identity, capabilities, policies and credentials.

The seller administrator should not need to understand A2A protocol internals, create a server, or deploy an agent manually. Verifund should guide them through a configuration wizard in the Seller Portal.

I recommend making the process part of the existing eight-step seller onboarding flow, with the A2A configuration and provisioning steps grouped together.

## 1. Overall onboarding sequence

## Seller onboarding lifecycle

1. Clerk authentication

   Seller administrator signs in using Clerk.

2. Organization selection

   Verifund resolves the active Clerk Organization and checks the user's membership and role.

3. Seller profile

   Collect business details and establish the seller tenant record.

4. A2A Seller Agent configuration

   Configure agent identity, instructions, capabilities, policies and autonomy.

5. Agent provisioning

   Create the logical agent identity, machine credentials and registry entry.

6. Integration and tool setup

   Connect catalog, inventory, pricing and other seller systems.

7. Agent testing

   Test catalog access, quotation generation and A2A communication.

8. Seller activation

   Approve and publish the Seller Agent for marketplace discovery.

A seller can save progress and return later. The agent should not become discoverable or accept commercial requests until the required setup and verification steps are complete.

## 2. Step one: establish the seller's organization after Clerk authentication

When the seller administrator signs in, Verifund should establish which organization they are configuring before showing the onboarding wizard.

### What happens technically

1. The user authenticates through Clerk.
2. The user selects or creates a Clerk Organization.
3. Next.js obtains the authenticated user's active `orgId` and `orgRole`.
4. The frontend calls the Verifund backend.
5. FastAPI validates the Clerk session/token and checks the user's organization membership and permissions.
6. Verifund looks up the corresponding internal tenant.
7. If no seller tenant exists, it creates an onboarding record associated with that organization.

Clerk Organizations support active organization context, membership roles, and organization switching.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://clerk.com&sz=32)

Clerk Docs+1

For example:

```
Clerk User
  user_123
      |
      v
Clerk Organization
  org_abc
  Name: TechSupply Inc.
  Role: org:admin
      |
      v
Verifund Backend
      |
      v
Internal Tenant
  tenant_id: tn_techsupply
  clerk_org_id: org_abc
  type: seller
  onboarding_status: in_progress
```

The important point is that `org_abc` and `tn_techsupply` are different identifiers.

Clerk owns the human organization identity. Verifund owns the internal tenant and commerce records.

### What the seller sees in the UI

Seller onboarding

Authenticated

TechSupply Inc.

Connected organization

ORGANIZATION DETAILS

Organization ID

org_abc

Your role

Administrator

Verifund tenant

tn_techsupply

The actual UI should display the organization name and onboarding status. Internal identifiers can remain in administrative diagnostics.

Only an authorized organization administrator or designated seller onboarding manager should be allowed to provision the organization's Seller Agent.

## 3. Step two: configure the Seller Agent identity

Once the seller profile is established, the onboarding wizard should introduce the agent.

I would label this screen Set up your AI Seller Agent.

The UI should explain that the agent represents the seller in Verifund's agent-to-agent marketplace.

The seller should configure its identity, not its server infrastructure.

### Suggested UI

Set up your Seller Agent

Step 4 of 8

TechSupply AI Sales Agent

Your autonomous commerce representative

Agent name

TechSupply Sales Agent

Agent description

Represents TechSupply Inc. in Verifund. Helps buyers discover products, request quotations, negotiate commercial terms and coordinate orders.

Agent type

Seller Agent

Selected

Agent visibility

Verifund marketplace

Discoverable by authorized Buyer Agents after activation.

This is an illustrative onboarding screen, not a live interactive form.

When the seller continues, Verifund generates the logical agent identity.

For example:

```
agent_id: agt_01JTECHSUPPLY
tenant_id: tn_techsupply
agent_type: seller
display_name: TechSupply Sales Agent
status: draft
```

The `agent_id` is permanent and should be independent of the agent's display name.

If the seller later renames the agent, its identity should not need to change.

## 4. Step three: configure agent instructions and behavior

The next screen should define how the Seller Agent behaves when interacting with Buyer Agents.

The seller should not need to write complicated system prompts. Provide a sensible default instruction template with optional customization.

For example:

Seller Agent instructions

Default instruction template for TechSupply Inc.

You are the AI sales representative for TechSupply Inc.

Your responsibilities are to:

- Help buyers discover suitable products and services.
- Retrieve accurate product and inventory information.
- Generate quotations using approved pricing policies.
- Negotiate commercial offers within authorized limits.
- Explain product availability and fulfillment options.
- Escalate requests that exceed your authority.

Never invent product availability, prices, discounts or delivery commitments.

Never disclose private seller information.

Never authorize payments or make commitments outside your assigned permissions.

Verifund can generate this template from the seller's business profile and allow authorized administrators to customize it.

I recommend storing instructions as versioned agent configuration, not hardcoding them into the shared Seller Agent runtime.

That means each seller can have different instructions while using the same underlying LangGraph workflow.

For example:

- TechSupply specializes in electronics procurement.
- OfficeWorld specializes in office supplies.
- FashionHub specializes in clothing and accessories.

Their agents can use different instructions and policies without requiring separate deployments.

## 5. Step four: select A2A capabilities and skills

This step determines what the Seller Agent advertises to Buyer Agents and what operations it is actually permitted to execute.

I would divide capabilities into two groups:

Advertised skills: What the agent claims it can help with.

Authorized tools: What the backend actually permits it to execute.

These must be related, but they are not interchangeable.

### Example capability configuration

Select Seller Agent capabilities

Enable the capabilities your organization wants to offer through A2A.

Product discovery

Search the seller's product catalog.

Enabled

Inventory checking

Check product availability.

Enabled

Quotation generation

Generate seller-approved quotations.

Enabled

Price negotiation

Respond to buyer offers and counteroffers.

Enabled

Agreement preparation

Prepare proposed commercial agreements.

Enabled

Order management

Coordinate authorized order creation.

Requires approval

You can map these to internal tool permissions:

```
catalog.search
product.read
inventory.check
pricing.quote
offer.create
offer.negotiate
agreement.propose
order.create
fulfillment.update
```

For example, a seller may advertise quotation generation but not permit autonomous order creation.

Verifund must enforce the actual permission check in FastAPI whenever a tool is called.

A2A Agent Cards describe agent capabilities and skills, but the Agent Card itself is not an authorization system.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com&sz=32)

GitHub+1

## 6. Step five: configure negotiation policies and autonomy

This is where the seller defines how much commercial authority the Seller Agent receives.

I recommend making this one of the most carefully designed onboarding screens.

The seller should configure pricing boundaries, discount limits, counteroffer rules and human approval requirements.

### Example: TechSupply negotiation policy

Negotiation policy

Define the limits within which the Seller Agent can negotiate.

Maximum discount

# 10%

Maximum discount the agent can offer without escalation.

Minimum selling price

# $1,350

For Developer Laptop Pro, per unit.

Autonomy mode

Policy-bounded

Negotiate within approved limits

The agent can generate quotations and counteroffers within configured rules. Exceptional requests are escalated to a human.

Human approval requirements

- Prices below minimum: always required.
- Discounts above 10%: always required.
- Non-standard payment terms: required.
- Agreement acceptance: according to seller authorization policy.
- Payment operations: never inferred from negotiation permission.

### Recommended autonomy options

| Mode                | Seller Agent authority                                                       |
| ------------------- | ---------------------------------------------------------------------------- |
| Read-only           | Search catalog and answer product questions                                  |
| Assisted            | Generate quotations and draft offers for approval                            |
| Policy-bounded      | Negotiate within seller-defined limits                                       |
| Advanced automation | Execute specifically authorized business operations within stricter policies |

I would make Policy-bounded the default.

A seller should be able to change these settings later from the Seller Agent workspace.

The effective permission model should be enforced by the backend:

\\[ P\_{\text{effective}} = P\_{\text{tenant}} \cap P\_{\text{agent}} \cap P\_{\text{run}} \\]

This ensures that an agent cannot exceed either the organization's permissions, its own assigned capabilities, or the authority granted for a specific execution.

## 7. Step six: configure the A2A connection

This is the point where Verifund prepares the agent for communication with external Buyer Agents.

The seller should not need to supply an A2A server URL or deploy a server.

Verifund manages the shared infrastructure.

For example:

```
A2A Gateway:
https://agents.verifund.com/a2a

Logical Seller Agent:
agt_01JTECHSUPPLY

A2A routing identifier:
agt_01JTECHSUPPLY

Hosting:
Verifund shared runtime
```

The seller's Agent Card is generated from its saved configuration.

### Example Agent Card

An illustrative A2A interface for TechSupply could look like this:

```
{
  "name": "TechSupply Sales Agent",
  "description": "Seller Agent for TechSupply Inc.",
  "supportedInterfaces": [
    {
      "url": "https://agents.verifund.com/a2a",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0",
      "tenant": "agt_01JTECHSUPPLY"
    }
  ],
  "capabilities": {
    "streaming": true
  },
  "skills": [
    {
      "id": "product-discovery",
      "name": "Product Discovery",
      "description": "Search TechSupply's available products."
    },
    {
      "id": "inventory-check",
      "name": "Inventory Check",
      "description": "Check authorized inventory availability."
    },
    {
      "id": "pricing-negotiation",
      "name": "Pricing Negotiation",
      "description": "Negotiate within seller-approved policies."
    }
  ]
}
```

This example illustrates the routing and skill structure; a production Agent Card must also include all required fields and the actual authentication requirements of the server.

### Why the `tenant` field matters

The A2A protocol supports multiple agents behind a shared endpoint. The `tenant` value in a `supportedInterfaces` entry is an opaque routing identifier. An A2A client must echo that value in requests to the selected interface.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://a2a-protocol.org&sz=32)

A2A Protocol+1

For Verifund:

```
TechSupply Agent Card
  endpoint: agents.verifund.com/a2a
  tenant: agt_01JTECHSUPPLY

OfficeWorld Agent Card
  endpoint: agents.verifund.com/a2a
  tenant: agt_01JOFFICEWORLD
```

Both use the same A2A gateway, but the gateway resolves each request to the correct logical seller agent.

Important: The routing identifier is not a secret or credential. Authentication must happen separately.

### What authentication should the Seller Agent use?

There are two authentication contexts:

1. The seller administrator authenticates through Clerk to configure and manage the agent.
2. A Buyer Agent authenticates as a machine client when communicating with the Seller Agent.

For the second context, Verifund should use a machine-to-machine credential strategy, such as scoped OAuth 2.0 access tokens or signed JWTs with appropriate issuer, audience, expiry and permissions.

Do not use the seller administrator's Clerk session token as the Seller Agent's permanent credential.

Also, do not expose machine credentials in the Seller Portal. The portal should show connection status and credential rotation controls, not the underlying secret.

## 8. Step seven: connect seller business data and integrations

A Seller Agent is only useful if it can access accurate seller information.

The onboarding wizard should therefore ask how the seller manages its products and operations.

For example, TechSupply might use:

- Verifund's built-in catalog.
- An external e-commerce platform.
- An ERP system.
- An inventory management system.
- A custom pricing API.

The Seller Agent should access these systems through authorized backend tools.

### Suggested integration screen

Connect your business systems

Choose the sources your Seller Agent can use.

Product catalog

Verifund catalog

Connected

Inventory

Inventory source

Not connected

Pricing

Seller pricing rules

Configured

Payment provider

PayPal seller integration

Optional setup

The integration layer should be separate from the agent instructions.

For example, the Seller Agent should not receive a raw database connection string. It should call `inventory.check`, and the backend should retrieve inventory for the correct tenant.

This is safer and makes it easier to replace or add external commerce providers.

## 9. Step eight: provision the agent and publish its Agent Card

When the seller completes the configuration, Verifund should provision the logical agent.

This should be a backend operation, not a frontend-generated identity.

The provisioning workflow should:

1. Validate the Clerk user's organization membership.
2. Validate the seller's onboarding permissions.
3. Verify that the seller tenant exists.
4. Validate the agent configuration.
5. Create the agent record.
6. Save the agent instructions and policy versions.
7. Assign its capabilities and tool permissions.
8. Create its machine identity.
9. Register the logical agent in the Verifund Agent Registry.
10. Generate its Agent Card.
11. Run configuration validation.
12. Set its status to `pending_test`.

The agent should not be marked `active` just because the database record was created.

### Suggested agent lifecycle

## Seller Agent lifecycle

1. Draft

   Draft

   Seller is configuring the agent.

2. Provisioning

   Provisioning

   Verifund creates its identity, configuration and registry record.

3. Pending test

   Pending test

   Configuration exists, but the agent has not passed its tests.

4. Active

   Active

   The agent is eligible for marketplace discovery and authorized A2A interactions.

5. Suspended / Revoked

   Restricted

   The agent cannot accept new requests until the issue is resolved or access is restored.

The Agent Registry should publish only approved discovery metadata. It should not expose private seller instructions, internal policies, API keys or credentials.

## 10. Step nine: test the Seller Agent before activation

Before publishing the agent to the marketplace, give the seller an interactive test workspace.

This is where the seller can verify that the agent behaves correctly.

I recommend including four test categories.

| Test          | What it verifies                                            |
| ------------- | ----------------------------------------------------------- |
| Identity test | Agent has the correct seller identity                       |
| Catalog test  | Agent retrieves the seller's products                       |
| Pricing test  | Agent respects pricing rules                                |
| A2A test      | Agent receives and responds to an authenticated A2A request |

### Example test scenario

The system could generate a sample request:

```
Buyer Agent:
I need 10 Developer Laptop Pro computers.

Can you provide:
- Current availability
- Wholesale pricing
- Estimated delivery time
```

The Seller Agent should return a response based on actual seller data:

```
TechSupply Sales Agent

Product: Developer Laptop Pro
Available quantity: 42
Standard price: $1,500
Wholesale price: $1,350
Estimated delivery: 5 business days

Total quotation: $13,500

Offer status: Awaiting buyer response
```

The test should verify that the agent:

- Does not invent availability.
- Does not exceed its pricing authority.
- Does not expose another tenant's data.
- Does not claim that a quotation is an accepted agreement.
- Does not initiate unauthorized payment operations.

Only after these checks pass should the seller be allowed to activate the agent.

# 11. How the backend should store the configuration

I recommend separating seller organization records, agent identity, agent configuration, policies, permissions and credentials.

A possible Neon PostgreSQL schema is:

Core database entities

organizations

`id`, `clerk_org_id`, `name`, `type`, `status`

agents

`id`, `tenant_id`, `agent_type`, `name`, `status`, `hosting_mode`

agent_configs

Instructions, model preferences, runtime configuration and version.

agent_policies

Pricing, autonomy, approval and negotiation policies.

agent_capabilities

Advertised skills and assigned tool permissions.

agent_credentials

Secret references, credential metadata and rotation status.

agent_registry_entries

`agent_id`, `card_url`, `endpoint`, `visibility`, `published_version`

You will also need tables for onboarding progress, integration connections, agent execution history and audit events.

A few important design decisions:

- Use the internal `tenant_id` as the ownership boundary.
- Keep `clerk_org_id` as an external identity reference.
- Store agent configurations as versioned records.
- Store secrets in a secret manager, not directly in PostgreSQL.
- Keep the public Agent Card separate from private agent configuration.
- Apply tenant-scoped database access and RLS to organization-owned data.

## 12. Backend API endpoints

The Next.js workspace should call FastAPI endpoints to perform each onboarding operation.

I would organize them like this:

| Endpoint                                   | Purpose                                  |
| ------------------------------------------ | ---------------------------------------- |
| `GET /api/me/organization`                 | Resolve the active organization          |
| `POST /api/seller/onboarding`              | Initialize seller onboarding             |
| `PATCH /api/seller/onboarding/profile`     | Save business profile                    |
| `POST /api/seller/agents`                  | Create a draft Seller Agent              |
| `PATCH /api/seller/agents/{id}/config`     | Save agent configuration                 |
| `PATCH /api/seller/agents/{id}/policies`   | Save negotiation policies                |
| `PUT /api/seller/agents/{id}/capabilities` | Configure capabilities                   |
| `POST /api/seller/agents/{id}/provision`   | Provision the agent                      |
| `POST /api/seller/agents/{id}/test`        | Run agent tests                          |
| `POST /api/seller/agents/{id}/activate`    | Activate the agent                       |
| `GET /api/seller/agents/{id}/status`       | Retrieve provisioning and runtime status |

### Example: provisioning request

The frontend might send:

```
POST /api/seller/agents/agt_01JTECHSUPPLY/provision
Authorization: Bearer <Clerk session token>
Content-Type: application/json
```

The body should contain only the requested operation and any user-editable provisioning options.

```
{
  "hosting_mode": "shared",
  "publish_to_registry": true
}
```

Notice that the frontend does not supply a trusted `tenant_id`, agent ownership or machine credential. FastAPI resolves the authenticated user's organization context and ownership itself.

### Example backend logic

```
async def provision_seller_agent(    agent_id: str,    current_user: AuthenticatedUser,    db: AsyncSession):    # 1. Resolve active organization from verified auth context    organization = await resolve_active_organization(        current_user    )    # 2. Resolve internal seller tenant    tenant = await get_seller_tenant(        db=db,        clerk_org_id=organization.clerk_org_id    )    # 3. Check organization permissions    await require_permission(        current_user,        "seller:agents:manage"    )    # 4. Resolve the agent within this tenant    agent = await get_agent(        db=db,        agent_id=agent_id,        tenant_id=tenant.id    )    # 5. Validate configuration and policies    await validate_agent_configuration(agent)    # 6. Create machine identity    credentials = await provision_machine_identity(agent)    # 7. Generate and register Agent Card
```

This is a simplified architectural example. The actual implementation should also handle idempotency, provisioning retries, credential rotation, rollback and registry failures.

# 13. How the complete UI should look after Clerk authentication

I would organize the seller onboarding interface into a wizard with a persistent progress indicator.

Verifund Seller Setup

Seller workspace

TechSupply Inc.

Authenticated organization

Connected

## Complete your seller setup

Configure your business and activate your AI sales representative.

Business profile

Completed

Done

Business verification

Completed

Done

03

Commerce integrations

In progress

04

AI Seller Agent

Next step

Upcoming

05

Negotiation policies

Pending

06

Payment configuration

Pending

07

Agent testing

Pending

08

Activate seller

Pending

Once the seller completes onboarding, the workspace should transition into the normal Seller Portal.

The Seller Agent page would then display:

- Agent name and identity.
- Agent status.
- A2A endpoint.
- Agent Card.
- Published capabilities.
- Negotiation policies.
- Tool permissions.
- Recent executions.
- A2A communication history.
- Credential rotation and security controls.

The seller can update its instructions and policies without creating a new server or replacing its logical agent identity.

# 14. Important distinction: Clerk authentication versus A2A authentication

This is probably the most important security distinction in the entire onboarding design.

| Operation                             | Identity used                                            |
| ------------------------------------- | -------------------------------------------------------- |
| Seller administrator signs in         | Clerk user identity                                      |
| Administrator switches organizations  | Clerk active organization                                |
| Administrator configures Seller Agent | Clerk-authenticated user + Verifund permissions          |
| Seller Agent calls its backend tools  | Agent machine identity                                   |
| Buyer Agent contacts Seller Agent     | Buyer Agent machine identity                             |
| Verifund routes an A2A request        | Logical agent identifier + authenticated request context |

Clerk should not be responsible for creating or authenticating every Seller Agent as if it were a human user.

Instead, Verifund should provision machine identities independently.

The A2A protocol describes authentication requirements through Agent Card security metadata, while the actual identity and authentication are handled at the transport layer.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com&sz=32)

GitHub+1

This means your Agent Card can be publicly discoverable, but the A2A endpoint can still require authenticated requests.

## 15. My recommended implementation for Verifund

I would use the following architecture:

## Clerk → Seller onboarding → A2A provisioning

Seller administrator

Signs in and selects organization

Clerk Organizations

Authenticates user and provides organization context

FastAPI onboarding service

Resolves tenant and checks seller permissions

Seller Agent provisioning

Agent identity

Instructions

Capabilities

Policies

Machine identity

Agent Card

Shared Verifund A2A Gateway

agents.verifund.com/a2a

Seller Agent active

Discoverable through the Agent Registry

I would also make one important product decision: seller onboarding should create and configure the Seller Agent automatically, rather than asking the seller to deploy or register an external A2A server.

The seller is configuring a business representative, not operating agent infrastructure.

This makes onboarding much easier for ordinary businesses while preserving the ability to support enterprise sellers with dedicated agent hosting later.

### Useful implementation references

- [Clerk Organizations — Next.js setup and organization roles](https://clerk.com/docs/guides/organizations/getting-started?utm_source=chatgpt.com)
- [A2A multi-tenancy and multi-agent routing](https://a2a-protocol.org/v1.0.1/topics/multi-tenancy/?utm_source=chatgpt.com)
- [A2A Agent Card specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md?utm_source=chatgpt.com)
- [A2A Agent Card capabilities, skills and security metadata](https://a2a-protocol.org/latest/specification/agent-card/?utm_source=chatgpt.com)

Recommended next implementation step: Build the seller onboarding wizard and FastAPI provisioning endpoints together, so completing the A2A configuration in the UI creates a real tenant-scoped Seller Agent record, rather than merely saving a frontend configuration.
