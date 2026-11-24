"use client";

import { useCallback } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";

const AGENT_ID = "marketmesh_orchestrator";

/** Shared by every trigger so two cards cannot dispatch in the same tick,
 * before CopilotKit has had a chance to set `agent.isRunning`. */
let dispatchInFlight = false;

/** Dispatch a run only when no run is already active on the current thread. */
export function useRunLaunch() {
  const { agent } = useAgent({ agentId: AGENT_ID });
  const { copilotkit } = useCopilotKit();

  const runOnActiveThread = useCallback(
    async (prepare?: () => void) => {
      if (dispatchInFlight || agent.isRunning) return false;
      dispatchInFlight = true;
      try {
        prepare?.();
        await copilotkit.runAgent({ agent });
        return true;
      } finally {
        dispatchInFlight = false;
      }
    },
    [agent, copilotkit],
  );

  return { runOnActiveThread };
}
