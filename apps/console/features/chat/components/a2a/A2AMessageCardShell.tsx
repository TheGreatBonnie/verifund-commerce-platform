"use client";

import React from "react";

export type A2ADirection = "outbound" | "inbound";

export type A2AMessageCardShellProps = {
  direction: A2ADirection;
  label?: string;
  timestamp?: string;
  statusText: string;
  statusTone?: "neutral" | "success" | "warning" | "danger";
  messageId?: string;
  taskId?: string;
  contextId?: string;
  expanded: boolean;
  onToggleExpanded: () => void;
  children: React.ReactNode;
  footerMetaLeft?: string;
};

export function A2AMessageCardShell({
  direction,
  label,
  timestamp,
  statusText,
  statusTone = "neutral",
  messageId,
  taskId,
  contextId,
  expanded,
  onToggleExpanded,
  children,
  footerMetaLeft,
}: A2AMessageCardShellProps) {
  const isOutbound = direction === "outbound";
  const isFailedTone = statusTone === "danger";

  const directionBadgeClass = isOutbound
    ? "bg-emerald-100 text-emerald-800"
    : isFailedTone
      ? "bg-red-100 text-red-800"
      : "bg-blue-100 text-blue-800";

  const containerClass = isOutbound
    ? "bg-emerald-50/60 border-emerald-200 a2a-message-card-outgoing"
    : isFailedTone
      ? "bg-red-50/60 border-red-200 a2a-message-card-incoming"
      : "bg-blue-50/60 border-blue-200 a2a-message-card-incoming";

  const detailsBorderClass = isOutbound ? "border-emerald-200/70" : isFailedTone ? "border-red-200/70" : "border-blue-200/70";
  const detailsBgClass = isOutbound
    ? "bg-emerald-50/40"
    : isFailedTone
      ? "bg-red-50/40"
      : "bg-blue-50/40";
  const headerBorderClass = detailsBorderClass;
  const footerTextClass = isFailedTone ? "text-red-700/80" : isOutbound ? "text-emerald-900/70" : "text-blue-900/70";

  const statusPillClass = isFailedTone
    ? "bg-white/60 text-red-700 border-red-200/70"
    : isOutbound
      ? "bg-white/60 text-emerald-900/80 border-emerald-200/70"
      : "bg-white/60 text-blue-900/80 border-blue-200/70";

  const metaLeft =
    footerMetaLeft ??
    `A2A message${messageId ? ` · ${messageId}` : taskId ? ` · ${taskId}` : ""}`;

  const hasDetails = Boolean(messageId || taskId || contextId);

  return (
    <div
      className={`my-2 overflow-hidden rounded-2xl border shadow-sm px-4 py-3 a2a-message-enter a2a-message-card ${containerClass}`}
    >
      <div className={`flex flex-wrap items-center gap-2 border-b pb-3 mb-3 ${headerBorderClass}`}>
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold tracking-wide ${directionBadgeClass}`}>
          {isOutbound ? "OUTBOUND" : "INBOUND"}
        </span>
        {label ? (
          <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold tracking-wide border ${statusPillClass}`}>
            {label}
          </span>
        ) : null}
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-medium border ${statusPillClass}`}>
          {statusText}
        </span>
        {timestamp ? <span className="ml-auto text-[11px] text-slate-500">{timestamp}</span> : null}
        <button
          type="button"
          aria-expanded={expanded}
          aria-label="Toggle message details"
          onClick={onToggleExpanded}
          className="ml-1 text-slate-400 hover:text-slate-700 text-sm leading-none"
        >
          {expanded ? "▴" : "▾"}
        </button>
      </div>

      <div className="a2a-message-layout">{children}</div>

      {hasDetails ? (
        <div className={`mt-4 border-t pt-3 ${detailsBorderClass}`}>
          {expanded ? (
            <div className={`mt-2 grid gap-2 rounded-xl border p-3 text-[11px] sm:grid-cols-3 ${detailsBorderClass} ${detailsBgClass}`}>
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

      <div className={`mt-4 border-t pt-2.5 flex items-center justify-between gap-2 text-[11px] ${detailsBorderClass} ${footerTextClass}`}>
        <span className="truncate">{metaLeft}</span>
        <span className="shrink-0 font-medium">{statusText}</span>
      </div>
    </div>
  );
}