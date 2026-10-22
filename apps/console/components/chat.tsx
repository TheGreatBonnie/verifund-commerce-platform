"use client";

import { useEffect } from "react";
import { CopilotChat, useFrontendTool, useAgent } from "@copilotkit/react-core/v2";
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

export function Chat({ onRunSample, isRunning, isReady, onBuyerStateUpdate }: ChatProps) {
  const { agent } = useAgent({ agentId: "a2a_chat" });

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

            // Check for MarketMesh buyer state fields
            if (parsed.status || parsed.award || parsed.mandate || parsed.task_id || parsed.order) {
              if (onBuyerStateUpdate) {
                onBuyerStateUpdate(parsed as BuyerState);
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
