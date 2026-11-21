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
  left?: { label: string; meta?: string };
  right: A2AAgentSide;
};

function avatarToneClasses(bgColor: string): string {
  // Map gradient/bg utility classes to a soft solid tone for the avatar circle.
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

export function A2AAgentPair({ left, right }: A2AAgentPairProps) {
  const agentStyle = getAgentStyle(right.name);
  const icon = right.icon ?? agentStyle.icon;
  const framework = right.framework ?? agentStyle.framework;

  const leftLabel = left?.label ?? "Orchestrator";
  const leftMeta = left?.meta ?? "ADK";

  // Orchestrator is fixed (Verifund/ADK context in this app) — use slate/neutral tone.
  const leftAvatarTone = "bg-slate-100 text-slate-700";
  const rightAvatarTone = avatarToneClasses(agentStyle.bgColor);

  return (
    <div className="a2a-message-route">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-sm ${leftAvatarTone}`} aria-hidden="true">
          🤖
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
          {icon}
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">{right.name}</div>
          {framework ? <div className="text-xs text-slate-500">{framework}</div> : null}
        </div>
      </div>
    </div>
  );
}
