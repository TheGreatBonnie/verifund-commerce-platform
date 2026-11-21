/**
 * Displays outgoing A2A messages (Orchestrator → Agent).
 * Green box with sender/receiver badges and task description.
 */

"use client";

import React, { useState } from "react";
import { truncateTask } from "./agent-styles";
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
    task?: string;
  };
};

export const MessageToA2A: React.FC<MessageActionRenderProps> = ({
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
}) => {
  // Hook must be unconditionally called before any early return.
  const displayName = useResolvedAgentName(args?.agentName) ?? args?.agentName;
  const [cardExpanded, setCardExpanded] = useState(false);
  const [textExpanded, setTextExpanded] = useState(false);

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
  const isLongTask = task.length > 50;
  const statusText = status === "executing" ? "Sending…" : statusLabel || "Delivered";

  return (
    <A2AMessageCardShell
      direction="outbound"
      label={label}
      timestamp={timestamp}
      statusText={statusText}
      statusTone="neutral"
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

      <div className="mt-3">
        <p className="text-gray-700 text-sm leading-6 a2a-message-copy" title={task}>
          {textExpanded || !isLongTask ? task : truncateTask(task)}
        </p>
        {isLongTask ? (
          <button
            type="button"
            onClick={() => setTextExpanded((v) => !v)}
            className="mt-1 text-[11px] font-medium text-emerald-800 hover:text-emerald-900"
          >
            {textExpanded ? "Show less" : "Show more"}
          </button>
        ) : null}
      </div>

      <A2APayload type={payloadType} data={payload} />
    </A2AMessageCardShell>
  );
};
