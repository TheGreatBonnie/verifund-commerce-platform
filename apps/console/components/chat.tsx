"use client";

import { useEffect } from "react";
import {
  CopilotChat,
  useAgent,
  useFrontendTool,
  useRenderTool,
} from "@copilotkit/react-core/v2";
import { z } from "zod";
import { ArrowUpRight, Sparkles } from "lucide-react";
import { MessageToA2A } from "./a2a/MessageToA2A";
import { MessageFromA2A } from "./a2a/MessageFromA2A";

type BuyerState = {
  status?: string;
  task_id?: string;
  stage?: string;
  award?: any;
  mandate?: any;
  order?: any;
  error?: any;
  message?: string;
};

type ChatProps = {
  onRunSample: () => void;
  isRunning: boolean;
  isReady: boolean;
  onBuyerStateUpdate?: (state: BuyerState) => void;
};

const SAMPLE_PROMPT =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

function sellerName(sellerId?: string, cardUrl?: string) {
  const names: Record<string, string> = {
    "northwind-audio": "Northwind Audio",
    circuitforge: "CircuitForge",
    "aurora-supply": "Aurora Supply",
  };
  if (sellerId && names[sellerId]) return names[sellerId];
  let port = "";
  try {
    port = cardUrl ? new URL(cardUrl).port : "";
  } catch {
    return sellerId ?? "Seller agent";
  }
  const idByPort: Record<string, string> = {
    "9201": "northwind-audio",
    "9202": "circuitforge",
    "9203": "aurora-supply",
  };
  return names[idByPort[port]] ?? sellerId ?? "Seller agent";
}

function requestSummary(request?: Record<string, unknown>) {
  const payload = (request?.payload ?? request) as Record<string, unknown> | undefined;
  if (!payload) return "Seller request";
  if (payload.product_hint) {
    return `RFQ · ${payload.quantity ?? ""} ${payload.product_hint}`.trim();
  }
  if (payload.target_unit_price_cents) {
    return `Counteroffer · $${(Number(payload.target_unit_price_cents) / 100).toFixed(2)} per unit`;
  }
  if (payload.accepted_total_cents) {
    return `Offer acceptance · $${(Number(payload.accepted_total_cents) / 100).toFixed(2)}`;
  }
  if (payload.offer_id) return `Order request · offer ${String(payload.offer_id)}`;
  return "Structured seller request";
}

function responseSummary(rawResult: string) {
  try {
    const content = rawResult.startsWith("A2A Agent Response: ")
      ? rawResult.slice("A2A Agent Response: ".length)
      : rawResult;
    const result = JSON.parse(content) as {
      error?: string;
      seller_result?: {
        offers?: Array<{ total_cents?: number }>;
        orders?: unknown[];
        order?: unknown;
      };
    };
    if (result.error) return { label: result.error, failed: true };
    const sellerResult = result.seller_result;
    if (!sellerResult) return { label: "Response received", failed: false };
    if (sellerResult.order || sellerResult.orders?.length) {
      return { label: "Order response received", failed: false };
    }
    const offers = sellerResult.offers ?? [];
    if (offers.length === 1 && offers[0].total_cents != null) {
      return {
        label: `Offer received · $${(offers[0].total_cents / 100).toFixed(2)}`,
        failed: false,
      };
    }
    if (offers.length > 1) {
      return { label: `${offers.length} offers received`, failed: false };
    }
    return { label: "Response received", failed: false };
  } catch {
    return { label: "Response received", failed: false };
  }
}

export function Chat({ onRunSample, isRunning, isReady, onBuyerStateUpdate }: ChatProps) {
  const { agent } = useAgent({ agentId: "a2a_chat" });

  useRenderTool({
    name: "mediate_seller_call",
    parameters: z.object({
      seller_id: z.string().optional(),
      seller_card_url: z.string(),
      seller_request: z.record(z.unknown()).optional(),
    }),
    render: ({ parameters, status, result }) => {
      if (status === "inProgress") return null;
      const agentName = sellerName(parameters.seller_id, parameters.seller_card_url);
      const outgoing = {
        agentName,
        task: requestSummary(parameters.seller_request),
      };
      const summary = status === "complete" ? responseSummary(result) : undefined;
      return (
        <div data-testid="mediated-seller-exchange">
          <MessageToA2A
            status={status === "executing" ? "executing" : "complete"}
            args={outgoing}
          />
          {summary ? (
            <MessageFromA2A
              status="complete"
              args={{ agentName }}
              response={summary.label}
              failed={summary.failed}
            />
          ) : null}
        </div>
      );
    },
  });

  // Extract structured JSON from A2A agent responses and pass to parent
  useEffect(() => {
    const extractDataFromMessages = () => {
      for (const message of agent.messages) {
        const msg = message as any;

        if (msg.role === "tool" && typeof msg.content !== "undefined") {
          try {
            const result = msg.content;
            let parsed;

            if (typeof result === "string") {
              let cleanResult = result;
              // Handle A2A response format from middleware
              if (result.startsWith("A2A Agent Response: ")) {
                cleanResult = result.slice("A2A Agent Response: ".length);
              }
              try {
                parsed = JSON.parse(cleanResult);
              } catch {
                continue;
              }
            } else if (typeof result === "object") {
              parsed = result;
            } else {
              continue;
            }

            // Mediation resumes the Buyer internally, so its latest state is
            // nested in the mediation tool result instead of a separate Buyer call.
            const buyerState = parsed.buyer_response ?? parsed;
            if (
              buyerState.status ||
              buyerState.award ||
              buyerState.mandate ||
              buyerState.task_id ||
              buyerState.order
            ) {
              if (onBuyerStateUpdate) {
                onBuyerStateUpdate(buyerState as BuyerState);
              }
            }
          } catch (e) {
            console.error("Failed to extract data from message:", e);
          }
        }
      }
    };

    extractDataFromMessages();
  }, [agent.messages, onBuyerStateUpdate]);

  useFrontendTool({
    name: "send_message_to_a2a_agent",
    description: "Sends a message to an A2A agent",
    available: true,
    parameters: z.object({
      agentName: z.string().describe("The name of the A2A agent to send the message to"),
      task: z.string().describe("The message to send to the A2A agent"),
    }),
    render: (actionRenderProps: {
      args?: { agentName?: string; task?: string };
      status?: string;
    }) => (
      <>
        <MessageToA2A {...actionRenderProps} />
        <MessageFromA2A {...actionRenderProps} />
      </>
    ),
  });

  return (
    <div className="mm-chat">
      <header className="mm-rail-head">
        <div>
          <p className="mm-kicker">Buyer agent · AG-UI</p>
          <h1>Brief desk</h1>
        </div>
        <span className="mm-agent-badge">
          <span className="mm-live-dot is-live" aria-hidden="true" /> Live
        </span>
      </header>

      <div className="mm-sample-brief">
        <div className="mm-sample-top">
          <span className="mm-kicker">
            <Sparkles size={12} aria-hidden="true" /> Demo mandate
          </span>
          <span className="mm-mono-note">consumer electronics</span>
        </div>
        <p>{SAMPLE_PROMPT}</p>
        <button
          type="button"
          className="mm-button mm-button-ink"
          onClick={onRunSample}
          disabled={isRunning || !isReady}
        >
          {isRunning ? "Agents working…" : "Run sample brief"}
          <ArrowUpRight size={14} aria-hidden="true" />
        </button>
      </div>

      <div className="mm-chat-surface">
        <CopilotChat
          agentId="a2a_chat"
          className="mm-copilot-chat"
          labels={{
            welcomeMessageText:
              "Tell me what your team needs. I’ll find independent sellers, negotiate structured offers, and stop for your approval before any order.",
            chatInputPlaceholder:
              "Describe the purchase, budget, deadline, and warranty…",
            chatDisclaimerText:
              "MarketMesh orchestrator · every order requires a human decision.",
          }}
        />
      </div>
    </div>
  );
}
