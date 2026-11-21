/**
 * Displays incoming A2A responses (Agent → Orchestrator).
 * Blue box with sender/receiver badges. Actual data renders separately in main UI.
 */

"use client";

import React, { useState } from "react";
import { getAgentStyle } from "./agent-styles";
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
  args,
  response,
  failed = false,
}) => {
  // Hook must be unconditionally called before any early return.
  const displayName = useResolvedAgentName(args?.agentName) ?? args?.agentName;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

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
  const hasDetails = Boolean(messageId || taskId || contextId);
  const baseText = failed
    ? response || "Seller call failed"
    : response || "Response received";
  const isLongText = baseText.length > 120;
  const derivedStatus = failed
    ? statusLabel || "Failed"
    : statusLabel || "Received";

  return (
    <div className="my-2 a2a-message-card a2a-message-card-incoming">
      <div
        className={`rounded-2xl px-4 py-3 border shadow-sm ${
          failed ? "bg-red-50/80 border-red-200" : "bg-blue-50/80 border-blue-200"
        }`}
      >
        <div className="a2a-message-layout">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <span
              className={`rounded-full px-2.5 py-1 text-[10px] font-bold tracking-wide ${
                failed ? "bg-red-100 text-red-800" : "bg-blue-100 text-blue-800"
              }`}
            >
              INBOUND
            </span>
            {label ? (
              <span
                className={`rounded-full bg-white/80 px-2.5 py-1 text-[10px] font-semibold tracking-wide border ${
                  failed ? "text-red-800 border-red-100" : "text-slate-600 border-blue-100"
                }`}
              >
                {label}
              </span>
            ) : null}
            <span
              className={`rounded-full px-2.5 py-1 text-[10px] font-medium border bg-white/70 ${
                failed ? "text-red-700 border-red-100" : "text-slate-600 border-blue-100"
              }`}
            >
              {failed ? "⚠ " : "✓ "}
              {derivedStatus}
            </span>
            {timestamp ? (
              <span className="ml-auto text-[11px] text-slate-500">{timestamp}</span>
            ) : null}
          </div>

          <div className="a2a-message-route">
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

            <span className="text-gray-400 text-sm" aria-hidden="true">→</span>

            <div className="flex flex-col items-center">
              <span className="px-3 py-1 rounded-full text-xs font-semibold bg-gray-700 text-white">
                Orchestrator
              </span>
              <span className="text-[9px] text-gray-500 mt-0.5">ADK</span>
            </div>
          </div>

          <div className="mt-3">
            <p className="text-sm leading-6 text-gray-700 a2a-message-copy">
              {expanded || !isLongText ? baseText : `${baseText.slice(0, 120)}…`}
            </p>
            {isLongText ? (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className={`mt-1 text-[11px] font-medium ${
                  failed ? "text-red-800 hover:text-red-900" : "text-blue-800 hover:text-blue-900"
                }`}
              >
                {expanded ? "Show less" : "Show more"}
              </button>
            ) : null}
          </div>

          {hasDetails ? (
            <div className={`mt-3 border-t pt-2 ${failed ? "border-red-100" : "border-blue-100"}`}>
              <button
                type="button"
                onClick={() => setDetailsOpen((v) => !v)}
                className="text-[11px] font-medium text-slate-600 hover:text-slate-800"
              >
                {detailsOpen ? "Hide details" : "Details"}
              </button>
              {detailsOpen ? (
                <div
                  className={`mt-2 grid gap-2 rounded-xl border p-3 text-[11px] sm:grid-cols-3 ${
                    failed ? "border-red-100 bg-white/70" : "border-blue-100 bg-white/70"
                  }`}
                >
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
    </div>
  );
};
