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

export function A2AAgentPair({ left, right }: A2AAgentPairProps) {
  const agentStyle = getAgentStyle(right.name);
  const icon = right.icon ?? agentStyle.icon;
  const framework = right.framework ?? agentStyle.framework;
  const badgeClassName =
    right.badgeClassName ??
    `${agentStyle.bgColor} ${agentStyle.textColor} ${agentStyle.borderColor}`;

  const leftLabel = left?.label ?? "Orchestrator";
  const leftMeta = left?.meta ?? "ADK";

  return (
    <div className="a2a-message-route">
      <div className="flex flex-col items-center">
        <span className="px-3 py-1 rounded-full text-xs font-semibold bg-gray-700 text-white">
          {leftLabel}
        </span>
        {leftMeta ? (
          <span className="text-[9px] text-gray-500 mt-0.5">{leftMeta}</span>
        ) : null}
      </div>

      <span className="text-gray-400 text-sm" aria-hidden="true">
        →
      </span>

      <div className="flex flex-col items-center">
        <span
          className={`px-3 py-1 rounded-full text-xs font-semibold border-2 flex items-center gap-1 ${badgeClassName}`}
        >
          <span>{icon}</span>
          <span>{right.name}</span>
        </span>
        {framework ? (
          <span className="text-[9px] text-gray-500 mt-0.5">{framework}</span>
        ) : null}
      </div>
    </div>
  );
}
