/**
 * Displays incoming A2A responses (Agent → Orchestrator).
 * Blue box with sender/receiver badges. Actual data renders separately in main UI.
 */

"use client";

import React, { useState } from "react";
import { useResolvedAgentName } from "./use-resolved-agent-name";
import { A2AAgentPair } from "./A2AAgentPair";
import { A2AMessageCardShell } from "./A2AMessageCardShell";
import { A2APayload, type A2APayloadType } from "./A2APayload";

type MessageActionRenderProps = {
  status?: string;
  timestamp?: string;
  label?: string;
  statusLabel?: string;
  messageId?: string;
  taskId?: string;
  contextId?: string;
  payloadType?: A2APayloadType;
  payload?: Record<string, unknown>;
  orchestratorLabel?: string;
  orchestratorMeta?: string;
  args?: {
    agentName?: string;
  };
  response?: string;
  failed?: boolean;
};

export const MessageFromA2A: React.FC<MessageActionRenderProps> = ({
  status,
  timestamp,
  label,
  statusLabel,
  messageId,
  taskId,
  contextId,
  payloadType,
  payload,
  orchestratorLabel,
  orchestratorMeta,
  args,
  response,
  failed = false,
}) => {
  // Hook must be unconditionally called before any early return.
  const displayName = useResolvedAgentName(args?.agentName) ?? args?.agentName;
  const [cardExpanded, setCardExpanded] = useState(false);
  const [textExpanded, setTextExpanded] = useState(false);

  switch (status) {
    case "complete":
      break;
    default:
      return null;
  }

  if (!args?.agentName) {
    return null;
  }

  const baseText = failed
    ? response || "Seller call failed"
    : response || "Response received";
  const isLongText = baseText.length > 120;
  const statusText = failed
    ? statusLabel
      ? `⚠ ${statusLabel}`
      : "⚠ Failed"
    : statusLabel
      ? `✓ ${statusLabel}`
      : "✓ Received";

  return (
    <A2AMessageCardShell
      direction="inbound"
      label={label}
      timestamp={timestamp}
      statusText={statusText}
      statusTone={failed ? "danger" : "neutral"}
      messageId={messageId}
      taskId={taskId}
      contextId={contextId}
      expanded={cardExpanded}
      onToggleExpanded={() => setCardExpanded((v) => !v)}
    >
      <A2AAgentPair
        left={{ label: orchestratorLabel ?? "Orchestrator", meta: orchestratorMeta ?? "ADK" }}
        right={{ name: displayName ?? args.agentName }}
      />

      <div className="mt-3 a2a-message-content">
        <p className="text-sm leading-6 text-slate-600 a2a-message-copy">
          {textExpanded || !isLongText ? baseText : `${baseText.slice(0, 120)}…`}
        </p>
        {isLongText ? (
          <button
            type="button"
            onClick={() => setTextExpanded((v) => !v)}
            className={`mt-1 text-[11px] font-medium ${
              failed ? "text-red-800 hover:text-red-900" : "text-blue-800 hover:text-blue-900"
            }`}
          >
            {textExpanded ? "Show less" : "Show more"}
          </button>
        ) : null}
      </div>

      <div className="a2a-message-content">
        <A2APayload type={payloadType} data={payload} />
      </div>
    </A2AMessageCardShell>
  );
};
