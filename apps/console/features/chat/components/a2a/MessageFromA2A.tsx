/**
 * Displays incoming A2A responses (Agent → Orchestrator).
 * Actual data renders separately in the main UI.
 */

"use client";

import React from "react";
import { cn } from "@/lib/cn";
import { getAgentStyle } from "./agent-styles";
import { useResolvedAgentName } from "./use-resolved-agent-name";

type MessageActionRenderProps = {
  status?: string;
  args?: {
    agentName?: string;
  };
  response?: string;
  failed?: boolean;
};

export const MessageFromA2A: React.FC<MessageActionRenderProps> = ({
  status,
  args,
  response,
  failed = false,
}) => {
  // Hook must be unconditionally called before any early return.
  const displayName = useResolvedAgentName(args?.agentName) ?? args?.agentName;

  switch (status) {
    case "complete":
      break;
    default:
      return null;
  }

  if (!args?.agentName) {
    return null;
  }
  const agentStyle = getAgentStyle(displayName ?? args.agentName);

  return (
    <div className="a2a-message-card mm-a2a-card mm-a2a-card--incoming">
      <div className="a2a-message-layout">
        <div className="a2a-message-route">
          <div className="mm-a2a-node">
            <span
              className={cn(
                "mm-agent-badge mm-a2a-badge",
                `mm-a2a-badge--${agentStyle.tone}`,
              )}
            >
              <span aria-hidden="true">{agentStyle.glyph}</span>
              <span>{displayName}</span>
            </span>
            {agentStyle.role ? (
              <span className="mm-kicker mm-a2a-role">{agentStyle.role}</span>
            ) : null}
          </div>

          <span className="mm-a2a-connector" aria-hidden="true">→</span>

          <div className="mm-a2a-node">
            <span className="mm-agent-badge mm-a2a-badge mm-a2a-badge--orchestrator">
              Orchestrator
            </span>
            <span className="mm-kicker mm-a2a-role">ADK</span>
          </div>
        </div>

        <span className={cn("mm-status mm-a2a-status", failed && "is-error")}>
          <span aria-hidden="true">{failed ? "⚠" : "✓"}</span>
          <span>{failed ? response || "Seller call failed" : response || "Response received"}</span>
        </span>
      </div>
    </div>
  );
};
