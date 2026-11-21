/**
 * Displays outgoing A2A messages (Orchestrator → Agent).
 * Green box with sender/receiver badges and task description.
 */

"use client";

import React, { useState } from "react";
import { getAgentStyle, truncateTask } from "./agent-styles";
import { useResolvedAgentName } from "./use-resolved-agent-name";

type MessageActionRenderProps = {
  status?: string;
  timestamp?: string;
  label?: string;
  statusLabel?: string;
  messageId?: string;
  taskId?: string;
  contextId?: string;
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
  args,
}) => {
  // Hook must be unconditionally called before any early return.
  const displayName = useResolvedAgentName(args?.agentName) ?? args?.agentName;
  const [expanded, setExpanded] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

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
  const isLongTask = task.length > 50;
  const derivedStatus =
    status === "executing" ? "Sending…" : statusLabel || "Delivered";
  const hasDetails = Boolean(messageId || taskId || contextId);

  return (
    <div className="bg-green-50/80 border border-green-200 rounded-2xl px-4 py-3 my-2 a2a-message-enter a2a-message-card a2a-message-card-outgoing shadow-sm">
      <div className="a2a-message-layout">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[10px] font-bold tracking-wide text-emerald-800">
            OUTBOUND
          </span>
          {label ? (
            <span className="rounded-full bg-white/80 px-2.5 py-1 text-[10px] font-semibold tracking-wide text-slate-600 border border-emerald-100">
              {label}
            </span>
          ) : null}
          <span className="rounded-full bg-white/70 px-2.5 py-1 text-[10px] font-medium text-slate-600 border border-emerald-100">
            {derivedStatus}
          </span>
          {timestamp ? (
            <span className="ml-auto text-[11px] text-slate-500">{timestamp}</span>
          ) : null}
        </div>

        <div className="a2a-message-route">
          <div className="flex flex-col items-center">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-gray-700 text-white">
              Orchestrator
            </span>
            <span className="text-[9px] text-gray-500 mt-0.5">ADK</span>
          </div>

          <span className="text-gray-400 text-sm" aria-hidden="true">→</span>

          <div className="flex flex-col items-center">
            <span
              className={`px-3 py-1 rounded-full text-xs font-semibold border-2 ${agentStyle.bgColor} ${agentStyle.textColor} ${agentStyle.borderColor} flex items-center gap-1`}
            >
              <span>{agentStyle.icon}</span>
              <span>{displayName}</span>
            </span>
            {agentStyle.framework && (
              <span className="text-[9px] text-gray-500 mt-0.5">
                {agentStyle.framework}
              </span>
            )}
          </div>
        </div>

        <div className="mt-3">
          <p className="text-gray-700 text-sm leading-6 a2a-message-copy" title={task}>
            {expanded || !isLongTask ? task : truncateTask(task)}
          </p>
          {isLongTask ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-[11px] font-medium text-emerald-800 hover:text-emerald-900"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          ) : null}
        </div>

        {hasDetails ? (
          <div className="mt-3 border-t border-emerald-100 pt-2">
            <button
              type="button"
              onClick={() => setDetailsOpen((v) => !v)}
              className="text-[11px] font-medium text-slate-600 hover:text-slate-800"
            >
              {detailsOpen ? "Hide details" : "Details"}
            </button>
            {detailsOpen ? (
              <div className="mt-2 grid gap-2 rounded-xl border border-emerald-100 bg-white/70 p-3 text-[11px] sm:grid-cols-3">
                {taskId ? (
                  <div>
                    <div className="text-slate-400">Task ID</div>
                    <div className="mt-0.5 font-medium text-slate-700 break-all">{taskId}</div>
                  </div>
                ) : null}
                {messageId ? (
                  <div>
                    <div className="text-slate-400">Message ID</div>
                    <div className="mt-0.5 font-medium text-slate-700 break-all">{messageId}</div>
                  </div>
                ) : null}
                {contextId ? (
                  <div>
                    <div className="text-slate-400">Context</div>
                    <div className="mt-0.5 font-medium text-slate-700 break-all">{contextId}</div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
};
