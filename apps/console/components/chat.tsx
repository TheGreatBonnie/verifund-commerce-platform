"use client";

import { CopilotChat, useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { ArrowUpRight, Sparkles } from "lucide-react";

type ChatProps = {
  onRunSample: () => void;
  isRunning: boolean;
  isReady: boolean;
};

const SAMPLE_PROMPT =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

function MessageToA2A({ args, status }: { args?: { agentName?: string; task?: string }; status?: string }) {
  return (
    <div className="my-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
      <div className="font-semibold">To {args?.agentName ?? "A2A agent"}</div>
      <div className="mt-1 break-words">{args?.task ?? ""}</div>
      {status ? <div className="mt-1 text-xs text-blue-700">{status}</div> : null}
    </div>
  );
}

function MessageFromA2A({ args, status }: { args?: { agentName?: string; task?: string }; status?: string }) {
  return (
    <div className="my-2 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900">
      <div className="font-semibold">From {args?.agentName ?? "A2A agent"}</div>
      <div className="mt-1 break-words">{args?.task ?? ""}</div>
      {status ? <div className="mt-1 text-xs text-green-700">{status}</div> : null}
    </div>
  );
}

export function Chat({ onRunSample, isRunning, isReady }: ChatProps) {
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
              "Buyer agent · every order requires a human decision.",
          }}
        />
      </div>
    </div>
  );
}
