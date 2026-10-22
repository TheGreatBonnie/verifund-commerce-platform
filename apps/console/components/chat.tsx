"use client";

import { CopilotChat } from "@copilotkit/react-core/v2";
import { ArrowUpRight, Sparkles } from "lucide-react";

type ChatProps = {
  onRunSample: () => void;
  isRunning: boolean;
  isReady: boolean;
};

const SAMPLE_PROMPT =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

export function Chat({ onRunSample, isRunning, isReady }: ChatProps) {
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
          agentId="marketmesh_buyer"
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
