/**
 * Displays outgoing A2A messages (Orchestrator → Agent).
 * Green box with sender/receiver badges and task description.
 */

"use client";

import React from "react";
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

  const displayName = useResolvedAgentName(args.agentName) ?? args.agentName;
  const task = args.task;
  const agentStyle = getAgentStyle(displayName);

  return (
    <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 my-2 a2a-message-enter a2a-message-card a2a-message-card-outgoing">
      <div className="a2a-message-layout">
        <div className="a2a-message-route">
          <div className="flex flex-col items-center">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-gray-700 text-white">
              Orchestrator
            </span>
            <span className="text-[9px] text-gray-500 mt-0.5">ADK</span>
          </div>

          <span className="text-gray-400 text-sm">→</span>

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

        <span
          className="text-gray-700 text-sm a2a-message-copy"
          title={task}
        >
          {truncateTask(task)}
        </span>
      </div>
    </div>
  );
};
