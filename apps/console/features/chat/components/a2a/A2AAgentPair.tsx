"use client";

import React from "react";
import { getAgentStyle } from "./agent-styles";

export type A2AAgentSide = {
  name: string;
  framework?: string;
  icon?: string;
  badgeClassName?: string;
};

export type A2AAgentPairProps = {
  left?: { label: string; meta?: string; icon?: string; name?: string };
  right?: { label: string; meta?: string; name?: string; icon?: string };
  /** When inbound, agent is on the left and Orchestrator on the right. */
  direction?: "outbound" | "inbound";
};

function avatarToneClasses(bgColor: string): string {
  if (bgColor.includes("indigo") || bgColor.includes("purple")) {
    return "bg-indigo-100 text-indigo-700";
  }
  if (bgColor.includes("blue") || bgColor.includes("cyan")) {
    return "bg-blue-100 text-blue-700";
  }
  if (bgColor.includes("amber") || bgColor.includes("orange")) {
    return "bg-amber-100 text-amber-700";
  }
  if (bgColor.includes("pink") || bgColor.includes("rose")) {
    return "bg-pink-100 text-pink-700";
  }
  if (bgColor.includes("teal") || bgColor.includes("emerald")) {
    return "bg-emerald-100 text-emerald-700";
  }
  return "bg-slate-100 text-slate-700";
}

export function A2AAgentPair({ left, right, direction = "outbound" }: A2AAgentPairProps) {
  const orchestratorLabel = direction === "inbound" ? right?.label ?? "Orchestrator" : left?.label ?? "Orchestrator";
  const orchestratorMeta = direction === "inbound" ? right?.meta ?? "ADK" : left?.meta ?? "ADK";

  const agentName =
    direction === "inbound"
      ? left?.label ?? left?.name ?? "Agent"
      : right?.label ?? right?.name ?? left?.name ?? left?.label ?? "Agent";

  const agentStyle = getAgentStyle(agentName);
  const agentIcon = direction === "inbound" ? left?.icon ?? agentStyle.icon : right?.icon ?? agentStyle.icon;
  const agentFramework = agentStyle.framework;

  const leftLabel = direction === "inbound" ? agentName : orchestratorLabel;
  const leftMeta = direction === "inbound" ? agentFramework : orchestratorMeta;
  const leftIcon = direction === "inbound" ? agentIcon : "🤖";
  const leftAvatarTone = direction === "inbound" ? avatarToneClasses(agentStyle.bgColor) : "bg-slate-100 text-slate-700";

  const rightLabel = direction === "inbound" ? orchestratorLabel : agentName;
  const rightMeta = direction === "inbound" ? orchestratorMeta : agentFramework;
  const rightIcon = direction === "inbound" ? "🤖" : agentIcon;
  const rightAvatarTone = direction === "inbound" ? "bg-slate-100 text-slate-700" : avatarToneClasses(agentStyle.bgColor);

  return (
    <div className="a2a-message-route">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-sm ${leftAvatarTone}`} aria-hidden="true">
          {leftIcon}
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">{leftLabel}</div>
          {leftMeta ? <div className="text-xs text-slate-500">{leftMeta}</div> : null}
        </div>
      </div>

      <span className="mx-1 shrink-0 text-slate-400 text-sm" aria-hidden="true">
        →
      </span>

      <div className="flex min-w-0 items-center gap-2.5">
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-base ${rightAvatarTone}`} aria-hidden="true">
          {rightIcon}
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">{rightLabel}</div>
          {rightMeta ? <div className="text-xs text-slate-500">{rightMeta}</div> : null}
        </div>
      </div>
    </div>
  );
}
