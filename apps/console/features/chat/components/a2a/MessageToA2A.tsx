/**
 * Displays outgoing A2A messages (Orchestrator → Agent).
 * Uses the Verifund console's panel/rule/mono language from agent-styles tones.
 */

"use client";

import React from "react";
import { cn } from "@/lib/cn";
import { getAgentStyle, truncateTask } from "./agent-styles";
import { useResolvedAgentName } from "./use-resolved-agent-name";

type MessageActionRenderProps = {
  status?: string;
  args?: {
    agentName?: string;
    task?: string;
  };
};

export const MessageToA2A: React.FC<MessageActionRenderProps> = ({
  status,
  args,
}) => {
  // Hook must be unconditionally called before any early return.
  const displayName = useResolvedAgentName(args?.agentName) ?? args?.agentName;

  switch (status) {
    case "executing":
    case "complete":
      break;
    default:
      return null;
  }

  if (!args?.agentName || !args?.task) {
    return null;
  }

  const task = args.task;
  const agentStyle = getAgentStyle(displayName ?? args.agentName);

  return (
    <div className="a2a-message-enter a2a-message-card mm-a2a-card mm-a2a-card--outgoing">
      <div className="a2a-message-layout">
        <div className="a2a-message-route">
          <div className="mm-a2a-node">
            <span className="mm-agent-badge mm-a2a-badge mm-a2a-badge--orchestrator">
              Orchestrator
            </span>
            <span className="mm-kicker mm-a2a-role">ADK</span>
          </div>

          <span className="mm-a2a-connector" aria-hidden="true">→</span>

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
        </div>

        <span
          className="a2a-message-copy mm-a2a-copy"
          title={task}
        >
          {truncateTask(task)}
        </span>
      </div>
    </div>
  );
};
