"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { useMemo } from "react";
import type { BuyerState } from "@/lib/types";
import { parseBuyerStateFromMessages } from "@/lib/runs";

export function useRunState() {
  const { agent } = useAgent({ agentId: "a2a_chat", updates: [] });
  const state = useMemo(
    () => parseBuyerStateFromMessages((agent.messages ?? []) as Array<{ role?: string; content?: unknown }>) ?? {},
    [agent.messages],
  );
  const stage = (state as BuyerState).stage ?? "new";
  const TERMINAL = new Set(["ordered", "rejected", "failed", "order_failed", "no_award"]);
  return {
    agent,
    state: state as BuyerState,
    stage,
    terminal: TERMINAL.has(stage),
    award: (state as BuyerState).award ?? null,
    mandate: (state as BuyerState).mandate ?? null,
    negotiations: (state as BuyerState).negotiations ?? [],
    sellers: (state as BuyerState).sellers ?? [],
    runId: (state as BuyerState).task_id ?? (state as BuyerState).run_id ?? agent.threadId ?? "",
  };
}
