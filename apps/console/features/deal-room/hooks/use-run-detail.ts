"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { UseAgentUpdate, useAgent } from "@copilotkit/react-core/v2";
import type { BuyerRun } from "@/lib/api";
import { parseBuyerStateFromMessages } from "@/lib/runs";
import type { BuyerState } from "@/lib/types";
import { useRegistry } from "@/features/sellers/use-registry";
import { useRun } from "@/features/runs/use-run";
import { useRunTrace } from "./use-run-trace";

const TERMINAL_STAGES = new Set([
  "ordered",
  "rejected",
  "failed",
  "order_failed",
  "no_award",
]);

const SAMPLE_BRIEF =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

function mergeRunState(state: BuyerState, run: BuyerRun | null): BuyerState {
  if (!run) return state;
  return {
    ...state,
    run_id: run.run_id ?? state.run_id,
    task_id: run.run_id ?? state.task_id,
    stage: run.stage ?? state.stage,
    mandate: run.mandate ?? state.mandate,
    award: run.award ?? state.award,
    order: run.order ?? state.order,
    error: run.error ?? state.error,
  };
}

export function useRunDetail(routeRunId: string) {
  const { agent, isReady } = useAgent({
    agentId: "a2a_chat",
    updates: [
      UseAgentUpdate.OnMessagesChanged,
      UseAgentUpdate.OnStateChanged,
      UseAgentUpdate.OnRunStatusChanged,
    ],
  });
  const [buyerState, setBuyerState] = useState<BuyerState>({});
  const [isRunning, setIsRunning] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [sellerFilter, setSellerFilter] = useState("all");
  const { run: buyerRun } = useRun(routeRunId);
  const { sellers: registry, isLoading: registryLoading, error: registryError, refresh: refreshRegistry } = useRegistry();

  useEffect(() => {
    if (routeRunId) agent.threadId = routeRunId;
  }, [agent, routeRunId]);

  useEffect(() => {
    const latest = parseBuyerStateFromMessages(
      (agent.messages ?? []) as Array<{ role?: string; content?: unknown }>,
    );
    if (latest) setBuyerState((current) => ({ ...current, ...latest }));
  }, [agent.messages]);

  const state = useMemo(
    () => mergeRunState(buyerState, buyerRun),
    [buyerState, buyerRun],
  );
  const stage = state.stage ?? "new";
  const terminal = TERMINAL_STAGES.has(stage);
  const traceRunId = routeRunId || state.task_id || state.run_id;
  const traceActive = hasStarted || Boolean(buyerRun);
  const trace = useRunTrace(traceRunId ?? "", traceActive, terminal);
  const events = trace.data ?? [];
  const traceError = trace.error ? "Trace feed unavailable" : null;

  const startRun = useCallback(
    async (brief: string) => {
      if (isRunning || !isReady) return;
      agent.threadId = routeRunId;
      agent.setMessages([]);
      agent.setState({});
      setBuyerState({});
      setRunError(null);
      setHasStarted(true);
      setSellerFilter("all");
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: brief,
      });
      setIsRunning(true);
      try {
        await agent.runAgent();
      } catch (error) {
        setRunError(
          error instanceof Error
            ? error.message
            : "The buyer agent could not start the run.",
        );
      } finally {
        setIsRunning(false);
      }
    },
    [agent, isReady, isRunning, routeRunId],
  );

  useEffect(() => {
    if (!isReady) return;
    let pendingBrief: string | null = null;
    try {
      pendingBrief = window.sessionStorage.getItem("marketmesh:pendingBrief");
      if (pendingBrief) window.sessionStorage.removeItem("marketmesh:pendingBrief");
    } catch {
      // Session storage is an optional bridge from the dashboard and sidebar.
    }
    if (pendingBrief) void startRun(pendingBrief);
  }, [isReady, startRun]);

  const onBuyerStateUpdate = useCallback((next: BuyerState) => {
    setBuyerState((current) => ({ ...current, ...next }));
  }, []);

  const sendApproval = useCallback(
    async (approved: boolean, note: string) => {
      const payload = {
        approval: { approved, approved_by: "Demo Buyer", note },
        task_id: buyerState.task_id ?? routeRunId,
      };
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: `MarketMesh approval response: ${JSON.stringify(payload)}`,
      });
      setIsRunning(true);
      try {
        await agent.runAgent();
      } catch (error) {
        setRunError(
          error instanceof Error
            ? error.message
            : "The approval could not be submitted.",
        );
      } finally {
        setIsRunning(false);
      }
    },
    [agent, buyerState.task_id, routeRunId],
  );

  const resetForRun = useCallback(
    (nextRunId: string) => {
      agent.threadId = nextRunId;
      agent.setMessages([]);
      agent.setState({});
      setBuyerState({});
      setRunError(null);
      setHasStarted(false);
      setSellerFilter("all");
    },
    [agent],
  );

  const onViewWire = useCallback((sellerId: string) => {
    setSellerFilter(sellerId);
    document.getElementById("a2a-wire")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }, []);

  const clearRunError = useCallback(() => setRunError(null), []);

  return {
    state,
    stage,
    award: state.award ?? null,
    mandate: state.mandate ?? null,
    negotiations: state.negotiations ?? [],
    sellers: state.sellers ?? [],
    runId: traceRunId ?? routeRunId,
    isReady,
    isRunning,
    runError,
    clearRunError,
    startRun: () => startRun(SAMPLE_BRIEF),
    resetForRun,
    sellerFilter,
    setSellerFilter,
    onViewWire,
    sendApproval,
    events,
    traceError,
    registry,
    registryLoading,
    registryError,
    refreshRegistry,
    onBuyerStateUpdate,
  };
}
