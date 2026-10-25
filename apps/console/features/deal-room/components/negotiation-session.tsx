"use client";

import { type ReactNode } from "react";
import {
  ArrowUpRight,
  Bot,
  Check,
  ChevronDown,
  FileText,
  MessageSquare,
  Store,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { shortId, stageLabel } from "@/lib/format";
import type { BuyerState } from "@/lib/types";

type NegotiationSessionProps = {
  children: ReactNode;
  state: BuyerState;
  runId: string;
  isReady: boolean;
  isRunning: boolean;
  onRunSample: () => void;
  logs: ReactNode;
  showLogs: boolean;
  onToggleLogs: () => void;
};

export function NegotiationSession({
  children,
  state,
  runId,
  isReady,
  isRunning,
  onRunSample,
  logs,
  showLogs,
  onToggleLogs,
}: NegotiationSessionProps) {
  const stage = state.stage ?? "new";
  const negotiations = state.negotiations ?? [];
  const sellers = state.sellers ?? [];
  const sellerCount = Math.max(sellers.length, negotiations.length);
  const approved = state.approval?.approved === true || stage === "ordered";
  const progress = [
    {
      label: "Brief received",
      detail: state.mandate?.product_hint ?? "Waiting for your requirements",
      done: Boolean(state.mandate),
    },
    {
      label: "Seller agents contacted",
      detail: sellerCount ? `${sellerCount} seller${sellerCount === 1 ? "" : "s"} in this run` : "Discovery pending",
      done: sellerCount > 0,
    },
    {
      label: "Offers negotiated",
      detail: state.award ? "Recommended offer ready" : negotiations.length ? "Comparing terms" : "Waiting for offers",
      done: Boolean(state.award),
    },
    {
      label: "Your approval",
      detail: approved ? "Approved" : stage === "awaiting_approval" ? "Awaiting your decision" : "Human approval required",
      done: approved,
    },
  ];

  return (
    <section className="mm-run-session" aria-labelledby="negotiation-session-title">
      <header className="mm-run-session-header">
        <div className="mm-run-session-heading">
          <span className="mm-run-session-icon" aria-hidden="true">
            <MessageSquare size={18} />
          </span>
          <div>
            <div className="mm-run-session-title-line">
              <h2 id="negotiation-session-title">Agent-to-agent negotiation</h2>
              <span className={`mm-session-state ${isRunning ? "is-active" : ""}`}>
                <span aria-hidden="true" /> {isRunning ? "Working" : isReady ? stageLabel(stage) : "Connecting"}
              </span>
            </div>
            <p>Your buyer agent is coordinating with seller agents and bringing the terms back for your review.</p>
          </div>
        </div>
        <div className="mm-run-session-actions">
          <Button
            variant="outline"
            size="sm"
            onClick={onToggleLogs}
            aria-expanded={showLogs}
            aria-controls="run-session-logs"
            leftIcon={<FileText size={12} aria-hidden="true" />}
          >
            {showLogs ? "Hide negotiation logs" : "Negotiation logs"}
            <ChevronDown size={12} aria-hidden="true" className={showLogs ? "is-rotated" : ""} />
          </Button>
          <Button
            size="sm"
            onClick={onRunSample}
            disabled={isRunning || !isReady}
            leftIcon={<ArrowUpRight size={12} aria-hidden="true" />}
          >
            Run sample
          </Button>
        </div>
      </header>

      <div className="mm-run-session-body">
        <aside className="mm-session-context" aria-label="Agents and negotiation progress">
          <article className="mm-session-agent is-buyer">
            <span className="mm-session-agent-icon" aria-hidden="true"><Bot size={18} /></span>
            <div>
              <h3>Buyer agent</h3>
              <p>{isRunning ? "Negotiating" : isReady ? "Ready for your brief" : "Connecting"}</p>
            </div>
            <span className={`mm-health-dot ${isReady ? "is-live" : ""}`} aria-label={isReady ? "Agent connected" : "Agent connecting"} />
            <span className="mm-session-agent-description">Finds sellers, negotiates terms, and protects your budget.</span>
          </article>

          <article className="mm-session-agent is-seller">
            <span className="mm-session-agent-icon" aria-hidden="true"><Store size={17} /></span>
            <div>
              <h3>{sellerCount > 1 ? "Seller agents" : "Seller agent"}</h3>
              <p>{sellerCount ? `${sellerCount} seller${sellerCount === 1 ? "" : "s"} contacted` : "Awaiting discovery"}</p>
            </div>
            <span className="mm-session-agent-description">Seller agents provide inventory, pricing, and fulfillment terms.</span>
          </article>

          <div className="mm-session-progress">
            <h3>Negotiation progress</h3>
            <ol>
              {progress.map((step, index) => (
                <li key={step.label} className={step.done ? "is-complete" : ""}>
                  <span className="mm-session-progress-mark" aria-hidden="true">
                    {step.done ? <Check size={11} /> : index + 1}
                  </span>
                  <span className="mm-session-progress-copy">
                    <strong>{step.label}</strong>
                    <small>{step.detail}</small>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </aside>

        <div className="mm-session-conversation">
          <div className="mm-session-conversation-head">
            <h3>Live conversation</h3>
            <span className="mm-mono-note">Run {shortId(runId, 12)}</span>
          </div>
          {children}
        </div>
      </div>

      <div className="mm-session-logs" id="run-session-logs" hidden={!showLogs}>
        {logs}
      </div>
    </section>
  );
}
