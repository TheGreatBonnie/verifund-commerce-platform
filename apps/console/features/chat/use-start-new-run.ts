"use client";

import { useCallback } from "react";
import { useThreads } from "@copilotkit/react-core/v2";

const AGENT_ID = "marketmesh_orchestrator";

/**
 * Start a brand-new conversation thread so a fresh procurement run never
 * reuses a thread whose Intelligence lock is still held by a previous run.
 */
export function useStartNewRun() {
  const { startNewThread } = useThreads({ agentId: AGENT_ID });

  const startNewRun = useCallback(() => {
    startNewThread();
  }, [startNewThread]);

  return { startNewRun };
}
