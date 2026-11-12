## Inspiration

I believe the future of commerce will increasingly involve AI agents acting on behalf of people. Instead of manually searching for products, comparing prices, contacting sellers, and negotiating deals, buyers will delegate these tasks to personal AI agents. Sellers will also use AI agents to represent their businesses, respond to inquiries, negotiate offers, and coordinate orders.

However, this emerging model introduces a fundamental problem: **How can buyers and sellers trust a transaction when their AI agents are negotiating and acting on their behalf?**

An agent can negotiate a great deal, but a successful negotiation does not guarantee that the seller will deliver what was promised. Similarly, buyers should not have to trust autonomous agents to authorize payments without clear boundaries, accountability, or protection.

I recognized that agentic commerce needs more than intelligent agents and seamless communication. It needs a reliable transaction layer that connects negotiated agreements to payment authorization, fulfillment, evidence, and accountability.

That realization inspired me to build **Verifund: the trust infrastructure for agentic commerce.**

## What it does

Verifund is an agentic commerce platform that enables buyers and sellers to transact through their own AI agents while introducing safeguards that make autonomous transactions more trustworthy.

A buyer can interact with a personal shopping agent through a conversational interface, describe what they need, establish a budget, and specify their requirements. The Buyer Agent discovers suitable products or services and communicates directly with independent Seller Agents through the Agent-to-Agent (A2A) protocol.

The agents exchange structured offers and counteroffers covering important transaction details such as pricing, product specifications, delivery requirements, warranties, and fulfillment conditions.

Once the agents reach an agreement, Verifund validates the negotiated terms and creates a structured transaction agreement. The buyer retains control by reviewing and explicitly approving the final agreement before payment is initiated.

PayPal integration connects the approved transaction to the payment workflow. After payment confirmation, Verifund tracks the seller's fulfillment obligations and collects evidence demonstrating whether the agreed conditions have been met.

The verification process evaluates submitted evidence against the transaction agreement rather than relying solely on the seller's claim that an order has been completed. Depending on the outcome, Verifund coordinates the appropriate next step, including payment release, additional evidence requests, or further review.

An important part of the experience is **Generative UI**. Instead of presenting every agent response as plain text, Verifund can render contextual interfaces based on the current task. These include product discovery cards, structured offers, negotiation summaries, agreement approval screens, fulfillment checklists, evidence review components, and transaction progress timelines.

I also designed the platform around **Human-in-the-Loop (HITL)** controls. Agents can autonomously perform routine discovery and negotiation within their assigned permissions, but consequential actions require appropriate human authorization or review.

Whether someone is purchasing a laptop, buying physical goods, or hiring a professional service, Verifund provides a consistent framework for turning autonomous negotiations into accountable transactions.

**I am not building another AI shopping assistant. I am building the trust and transaction layer that makes agent-to-agent commerce practical.**

## How I built it

I designed Verifund around a modular architecture that separates AI agent intelligence, agent communication, transaction governance, user interaction, and payment operations.

The frontend uses **Next.js 16, TypeScript, React, and Tailwind CSS** to provide the interfaces through which buyers and sellers interact with the platform, review agreements, monitor transactions, and manage fulfillment.

An important frontend capability is Generative UI. The interface is designed to respond to the context and output of agent workflows rather than relying exclusively on static chat messages. For example, when an agent discovers products, the interface can present structured product cards. When negotiations produce an offer, the buyer can see a comparison and agreement summary. When a seller submits fulfillment evidence, the interface can display requirement-specific evidence components and verification statuses.

At the AI layer, I use **LangChain and LangGraph** to structure agent capabilities and coordinate stateful workflows. LangChain provides the foundation for model interactions and tool integration, while LangGraph manages workflow execution, state transitions, conditional routing, and checkpointing.

The architecture separates the Buyer Agent and Seller Agent because they represent different participants with different responsibilities and authority. The Buyer Agent represents the buyer's requirements and purchasing constraints, while the Seller Agent represents the seller's catalog, pricing, availability, and fulfillment capabilities.

For interoperability, I use the **A2A protocol** to facilitate communication between independent agents. This allows buyer and seller agents to exchange quote requests, offers, counteroffers, and task results without requiring them to share the same internal framework. MCP complements this architecture by providing a standardized approach for connecting agents to authorized tools and resources where applicable.

**Human-in-the-Loop is incorporated into the workflow orchestration rather than treated as a separate feature.** Using LangGraph's interrupt and resume capabilities, the workflow can pause when buyer authorization is required, wait for a human decision, and resume from the appropriate checkpoint. The same principle applies to ambiguous fulfillment evidence and exceptional transaction decisions.

For persistence, I use **Neon PostgreSQL** as the relational data foundation for users, agents, shopping requests, offers, agreement versions, approvals, transactions, payment references, fulfillment evidence, and transaction activity. This gives Verifund an authoritative record independent of the agents' conversations.

For financial operations, I integrate **PayPal Sandbox** to demonstrate the checkout and payment lifecycle. The backend manages order creation, buyer approval, payment capture, and the separate seller payout workflow. Verifund maintains its own internal transaction and ledger states to track payment confirmation and whether release is permitted.

Finally, the fulfillment verification layer connects seller-submitted evidence to the requirements recorded in the transaction agreement. This makes it possible to distinguish between evidence that has merely been submitted, evidence that has passed verification, and cases requiring further review.

Together, these components form a coordinated transaction lifecycle in which agent intelligence, dynamic user interfaces, human authorization, and payment operations work together.

## Challenges I ran into

One of my biggest challenges was connecting autonomous agent behavior to financial operations that require predictable and enforceable rules.

**Agent interoperability and negotiation** presented an important architectural challenge. Independent agents may use different frameworks, instructions, and internal workflows. I needed a communication approach that would allow them to exchange meaningful commerce information without assuming they shared the same internal implementation. I addressed this by separating A2A communication from Verifund's application-level transaction structures.

Another challenge was **preventing autonomous negotiations from becoming unauthorized purchases**. An agent agreeing to a price should not automatically trigger payment. This required separating negotiation, agreement validation, buyer authorization, and payment execution into distinct stages.

**Human oversight and workflow orchestration** introduced another consideration. A human approval cannot simply be another conversational response that the agent interprets as permission. It must be associated with the correct transaction and agreement version. I designed the workflow around explicit approval checkpoints and resumable execution.

**Generative UI** also required a different way of thinking about the frontend. Rather than treating the interface as a collection of static pages, I needed to connect agent outputs and workflow states to meaningful visual components. The challenge is ensuring that dynamic interfaces remain consistent with authoritative backend transaction data.

Payment coordination introduced further complexity. Payment initiation, authorization, capture, and seller payout are distinct events that require reliable records and careful reconciliation.

Finally, fulfillment verification required me to think beyond a simple delivered/not-delivered status. Different products and services require different evidence. A laptop purchase may require delivery confirmation, product photographs, serial-number matching, and specification checks, while a professional service may require deliverables and completion evidence.

These challenges reinforced the importance of building trust into the transaction architecture rather than adding it as an afterthought.

## Accomplishments that I'm proud of

I am particularly proud of designing Verifund around a problem that will become increasingly important as commerce moves toward autonomous AI interactions.

My key accomplishments include:

- Designing a buyer-to-seller agent commerce architecture built around A2A communication.
- Using LangChain and LangGraph to structure agent capabilities and stateful workflows.
- Connecting autonomous negotiation to structured, versioned transaction agreements.
- Incorporating Human-in-the-Loop checkpoints for buyer authorization and exceptional decisions.
- Designing Generative UI experiences that transform agent outputs into contextual commerce interfaces.
- Integrating PayPal Sandbox into the transaction payment workflow.
- Designing a fulfillment evidence model that connects seller obligations to the conditions agreed upon by both parties.
- Establishing a transaction lifecycle that separates payment confirmation, fulfillment verification, and seller payout.
- Extending the concept beyond traditional freelance marketplaces to support both physical goods and professional services.

What makes me particularly proud is the underlying design principle: **AI agents can negotiate autonomously, but consequential financial decisions must remain governed by clear permissions, verified conditions, and accountable transaction rules.**

## What I learned

Building Verifund taught me that agentic commerce requires more than connecting multiple AI agents.

I learned that agent interoperability is essential when different businesses and individuals operate their own agents. A2A provides a communication foundation, while structured application-level agreements make their interactions meaningful for real transactions.

I also learned that frameworks such as LangGraph are valuable when agent workflows need durable state, conditional execution, checkpoints, and human approval. Autonomous workflows must be able to pause, wait for decisions, and resume without losing their transaction context.

Another important lesson was the value of Generative UI. AI applications do not have to limit users to conversational interfaces. Context-aware interfaces can make complex agent operations easier to understand by presenting information in the format most appropriate to the task.

I also learned that payment workflows must be treated as stateful processes. Payment initiation, authorization, capture, payout, and refund are distinct events that require reliable records and careful reconciliation.

Most importantly, I learned that **trust in autonomous commerce is an architectural responsibility**. It must be built into agent permissions, agreements, human oversight, payment operations, evidence handling, and transaction history.

## What's next for Verifund

I see Verifund evolving into an interoperable trust and transaction infrastructure for the wider agentic commerce ecosystem.

My next steps include expanding support for independent agents and additional A2A-compatible frameworks, integrating more commerce platforms, and strengthening the verification engine to handle increasingly diverse products and professional services.

I also plan to develop more advanced evidence analysis, automated dispute-resolution workflows, seller reputation mechanisms, and more sophisticated Generative UI experiences that adapt to different transaction stages and agent activities.

On the financial side, I aim to move beyond Sandbox demonstrations toward production-ready payment and settlement arrangements supported by appropriate provider capabilities, operational controls, and regulatory requirements.

Ultimately, I want Verifund to become the layer that allows compatible buyer and seller agents to transact with confidence, regardless of the marketplace, messaging platform, or agent framework they use.

**As AI agents become active participants in commerce, Verifund will provide the trust infrastructure that connects what agents agree to with what actually happens.**
