No, every seller does not need its own server URL. For Verifund, I recommend using one shared, multi-tenant Seller Agent service with dynamically resolved seller context, rather than deploying a separate A2A server for every seller.

Each seller can still have its own logical Seller Agent identity, Agent Card, policies, tools, and data access—even when all those agents are served by the same backend infrastructure.

This distinction is important:

- Physical deployment: Where the agent software runs.
- Logical agent identity: Which seller the agent represents.
- Tenant context: Which seller's data and policies the current request can access.

These do not have to be one-to-one.

## 1. Recommended model: one shared A2A endpoint, many seller agents

For example, Verifund could operate a shared A2A endpoint:

```
https://agents.verifund.com/a2a
```

All seller agents communicate through this endpoint, but each seller has a separate logical identity.

Verifund A2A Gateway

agents.verifund.com/a2a

Resolve recipient identity and authenticate request

Shared Seller Agent Runtime

Seller Agent A

TechSupply Inc.

Tenant A

Seller Agent B

OfficeWorld Ltd.

Tenant B

Seller Agent C

FashionHub

Tenant C

Seller Agent N

Other sellers

Tenant N

Tenant-scoped tools

Catalog, inventory, pricing, offers and orders.

Tenant-scoped data

Policies, agent configuration and business records.

One deployment and endpoint can serve many independently configured seller agents.

For example:

| Seller           | Logical agent ID    | A2A endpoint              |
| ---------------- | ------------------- | ------------------------- |
| TechSupply Inc.  | `agent_techsupply`  | `agents.verifund.com/a2a` |
| OfficeWorld Ltd. | `agent_officeworld` | `agents.verifund.com/a2a` |
| FashionHub       | `agent_fashionhub`  | `agents.verifund.com/a2a` |

The recipient agent ID determines which seller the request is intended for. The endpoint alone does not determine the seller.

## 2. How A2A supports this

This is not just a custom Verifund workaround. The A2A protocol explicitly supports multi-agent routing behind a shared endpoint.

The current A2A multi-tenancy guidance describes three approaches:

1. URL-based routing: Different paths on the same domain.
2. Authentication-based routing: The gateway identifies the target agent from the authenticated credential.
3. Tenant-field routing: Multiple agents share the same URL, and the request carries an advertised routing identifier in the A2A `tenant` field.&#x20;

   [image](https://www.google.com/s2/favicons?domain=https://a2a-protocol.org&sz=32)

   A2A Protocol+1

For Verifund, I would primarily use the third approach, combined with authenticated requests.

### Example: two seller Agent Cards

TechSupply Inc. could have this interface:

```
{
  "name": "TechSupply Seller Agent",
  "supportedInterfaces": [
    {
      "url": "https://agents.verifund.com/a2a",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0",
      "tenant": "agent_techsupply"
    }
  ]
}
```

OfficeWorld Ltd. could have:

```
{
  "name": "OfficeWorld Seller Agent",
  "supportedInterfaces": [
    {
      "url": "https://agents.verifund.com/a2a",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0",
      "tenant": "agent_officeworld"
    }
  ]
}
```

Notice that both cards advertise the same endpoint. The `tenant` value distinguishes the intended logical agent.

An A2A client reads the selected interface and echoes its `tenant` value in requests to that interface. The server interprets that value for routing. It is an opaque routing identifier, not an authentication credential.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://a2a-protocol.org&sz=32)

A2A Protocol+1

This means you can register hundreds or thousands of seller agents without necessarily deploying hundreds or thousands of A2A servers.

## 3. How Verifund should dynamically resolve each seller

I would make the seller agent a configurable, tenant-scoped agent runtime.

Instead of creating a separate codebase or server for each seller, Verifund stores each seller's agent configuration in PostgreSQL.

For example:

`agents` table

| agent_id      | tenant_id | name              | status |
| ------------- | --------- | ----------------- | ------ |
| agent_tech    | tn_001    | TechSupply Agent  | Active |
| agent_office  | tn_002    | OfficeWorld Agent | Active |
| agent_fashion | tn_003    | FashionHub Agent  | Active |

`agent_configurations` table

| agent_id      | model   | autonomy       |
| ------------- | ------- | -------------- |
| agent_tech    | Model A | Approval-based |
| agent_office  | Model B | Policy-bounded |
| agent_fashion | Model A | Read-only      |

`agent_policies` table

| agent_id      | policy       | value |
| ------------- | ------------ | ----- |
| agent_tech    | max_discount | 10%   |
| agent_office  | max_discount | 15%   |
| agent_fashion | max_discount | 5%    |

You could also store each seller's:

- Agent instructions.
- Product categories.
- Tool permissions.
- Pricing rules.
- Negotiation limits.
- Human escalation requirements.
- Integration references.
- Operating hours.
- Supported fulfillment methods.

The shared agent runtime loads the correct configuration when a request is received.

### Example request flow

1. Buyer Agent sends an A2A request

   Recipient: `agent_tech`

2. Verifund A2A Gateway receives it

   Shared endpoint: `agents.verifund.com/a2a`

3. Gateway authenticates the caller

   Validates the buyer agent's machine identity and request permissions.

4. Agent resolver identifies the seller

   Maps `agent_tech` to TechSupply Inc. and its tenant.

5. Runtime loads seller configuration

   Loads TechSupply's instructions, tools, pricing rules and negotiation policies.

6. Seller Agent executes

   Checks TechSupply's catalog and inventory, then generates an authorized response.

7. Verifund records the result

   Stores the negotiation event against the correct tenant and transaction context.

The next request might target OfficeWorld. The same runtime loads OfficeWorld's configuration instead.

The agent code is shared; the identity, policy, data and permissions are different.

## 4. How I would implement the Verifund backend

I recommend separating the following components:

| Component                   | Responsibility                                         |
| --------------------------- | ------------------------------------------------------ |
| A2A Gateway                 | Receives and routes A2A requests                       |
| Agent Resolver              | Maps agent identity to its seller tenant               |
| Agent Runtime               | Executes the shared Seller Agent workflow              |
| Agent Configuration Service | Loads seller-specific configuration                    |
| Tool Authorization          | Determines which seller tools can be executed          |
| Seller Data Service         | Retrieves tenant-scoped catalog, inventory and pricing |
| LangGraph                   | Orchestrates the agent's reasoning and workflow        |
| Neon PostgreSQL             | Stores agent configuration and business records        |
| Secret Manager              | Stores seller integration credentials                  |

A simplified implementation could look like this:

```
async def handle_a2a_request(request, authenticated_caller):    # 1. Read the A2A routing identifier    agent_id = request.tenant    # 2. Resolve the intended seller agent    agent = await agent_service.get_agent(agent_id)    if not agent or agent.status != "active":        raise AgentNotAvailableError()    # 3. Authorize the caller to contact this agent    await authorization_service.check_a2a_access(        caller=authenticated_caller,        recipient_agent=agent    )    # 4. Load seller-specific configuration    config = await agent_config_service.get_config(        agent_id=agent.id,        tenant_id=agent.tenant_id    )    # 5. Create an isolated execution context    context = AgentContext(        agent_id=agent.id,        tenant_id=agent.tenant_id,        policies=config.policies,        capabilities=config.capabilities    )    # 6. Execute the shared LangGraph workflow    result = await seller_agent_graph.ainvoke(        request.message,        config={            "configurable": {                "thread_id": create_isolated_thread_id()            }        },        context=context    )    # 7. Return the A2A response    return build_a2a_response(result)
```

This is illustrative Python, not a complete A2A server implementation.

One important security detail: Never trust the incoming `tenant` routing value as proof that the request is authorized to access that tenant. It only identifies the intended recipient. Verifund must authenticate the calling agent, resolve the recipient through its own trusted registry/database, and enforce access policies before executing any seller tools.

Also, every execution must have isolated state. TechSupply's conversation history, LangGraph memory, credentials and tool results must never leak into OfficeWorld's execution.

## 5. Should every seller have its own Agent Card?

Recommended

&#x20;Yes. Give each seller a distinct logical Agent Card, even if they share the same server URL.

The Verifund Agent Registry could contain:

```
Agent Registry
│
├── agent_techsupply
│   ├── seller: TechSupply Inc.
│   ├── endpoint: agents.verifund.com/a2a
│   ├── tenant routing: agent_techsupply
│   └── capabilities: catalog, inventory, pricing, negotiation
│
├── agent_officeworld
│   ├── seller: OfficeWorld Ltd.
│   ├── endpoint: agents.verifund.com/a2a
│   ├── tenant routing: agent_officeworld
│   └── capabilities: catalog, inventory, pricing, negotiation
│
└── agent_fashionhub
    ├── seller: FashionHub
    ├── endpoint: agents.verifund.com/a2a
    ├── tenant routing: agent_fashionhub
    └── capabilities: catalog, pricing, negotiation
```

This lets a Buyer Agent discover and select individual seller agents without needing to know how Verifund deploys them internally.

A2A supports publishing separate Agent Cards for agents hosted behind a shared domain.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://a2a-protocol.org&sz=32)

A2A Protocol+1

## 6. When would a seller need its own server?

There are situations where dedicated deployments make sense.

| Requirement                                          | Recommended deployment                     |
| ---------------------------------------------------- | ------------------------------------------ |
| Ordinary Verifund seller                             | Shared runtime                             |
| Seller with custom negotiation policies              | Shared runtime with custom configuration   |
| Seller with unique tools or integrations             | Shared runtime with isolated tool adapters |
| Enterprise seller requiring dedicated infrastructure | Dedicated runtime                          |
| Seller requiring private network connectivity        | Dedicated or private deployment            |
| Seller requiring strict data residency or isolation  | Deployment designed for that requirement   |

You can therefore support both models.

## Verifund hybrid agent hosting

Verifund Agent Registry

Discovers and resolves all seller agents

Shared hosting

Default

One A2A gateway and shared runtime.

- Seller A
- Seller B
- Seller C
- Seller N

Dedicated hosting

Enterprise

Separate deployment where required.

- Enterprise Seller X
- Private Seller Y

Both hosting models can be discovered through the same registry and coordinated by Verifund.

## 7. My final recommendation for Verifund

I would adopt this model:

Recommended architecture

# One shared A2A infrastructure, many independent Seller Agents

- One shared A2A Gateway.
- One scalable Seller Agent runtime.
- One logical Seller Agent per seller organization.
- One Agent Card per logical Seller Agent.
- One seller-specific configuration and policy set.
- Tenant-isolated tools, credentials, data and execution state.
- Optional dedicated hosting for enterprise sellers.

This gives Verifund several advantages:

1. Scalability: You can onboard many sellers without provisioning a server for every seller.
2. Lower infrastructure costs: Shared compute and deployment infrastructure.
3. Simpler onboarding: Provisioning a seller agent becomes primarily a database and configuration operation.
4. Centralized maintenance: You can update the common Seller Agent workflow once.
5. Seller independence: Each seller retains its own agent identity, catalog, pricing, policies and permissions.
6. Enterprise flexibility: Sellers that need dedicated infrastructure can receive it without changing the overall architecture.

The most important distinction is that one shared Seller Agent runtime does not mean one shared seller identity or one shared seller context.

Verifund should have many independently addressable Seller Agents, even if they are all powered by the same underlying LangGraph workflow and served through one A2A endpoint.

For the protocol details, see the [A2A Multi-Tenancy and Multi-Agent Routing guide](https://a2a-protocol.org/latest/topics/multi-tenancy/?utm_source=chatgpt.com) and the [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md?utm_source=chatgpt.com).
