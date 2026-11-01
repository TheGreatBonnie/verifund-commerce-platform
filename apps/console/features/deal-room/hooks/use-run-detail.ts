"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  UseAgentUpdate,
  useAgent,
  useCopilotKit,
} from "@copilotkit/react-core/v2";
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
  // Prefer a run award that still has a `winner`; otherwise keep the
  // in-memory display award so a winner-less (settlement) award can't
  // overwrite it.
  let award = run.award ?? state.award;
  if (award && !award.winner && state.award?.winner) {
    award = state.award;
  }
  return {
    ...state,
    run_id: run.run_id ?? state.run_id,
    task_id: run.run_id ?? state.task_id,
    stage: run.stage ?? state.stage,
    mandate: run.mandate ?? state.mandate,
    award,
    order: run.order ?? state.order,
    error: run.error ?? state.error,
  };
}

export function useRunDetail(routeRunId: string) {
  const { agent, isReady } = useAgent({
    agentId: "marketmesh_orchestrator",
    updates: [
      UseAgentUpdate.OnMessagesChanged,
      UseAgentUpdate.OnStateChanged,
      UseAgentUpdate.OnRunStatusChanged,
    ],
  });
  const { copilotkit } = useCopilotKit();
  const [buyerState, setBuyerState] = useState<BuyerState>({});
  const [isRunning, setIsRunning] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [sellerFilter, setSellerFilter] = useState("all");
  const { run: buyerRun, refresh: refreshRun } = useRun(routeRunId);
  const {
    sellers: registry,
    isLoading: registryLoading,
    error: registryError,
    refresh: refreshRegistry,
  } = useRegistry();

  useEffect(() => {
    if (routeRunId) agent.threadId = routeRunId;
  }, [agent, routeRunId]);

  useEffect(() => {
    const latest = parseBuyerStateFromMessages(
      (agent.messages ?? []) as Array<{ role?: string; content?: unknown }>,
    );
    if (latest) {
      setBuyerState((current) => {
        const merged = { ...current, ...latest };
        // Preserve the display award (AwardPackage with `winner`) when an
        // incoming update carries a settlement award (AwardRequest) that has
        // no `winner`, so the UI never renders a winner-less award.
        if (latest.award && !latest.award.winner && current.award?.winner) {
          merged.award = current.award;
        }
        return merged;
      });
    }
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
        await copilotkit.runAgent({ agent });
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
    [agent, copilotkit, isReady, isRunning, routeRunId],
  );

  useEffect(() => {
    if (!isReady) return;
    let pendingBrief: string | null = null;
    try {
      pendingBrief = window.sessionStorage.getItem("marketmesh:pendingBrief");
      if (pendingBrief)
        window.sessionStorage.removeItem("marketmesh:pendingBrief");
    } catch {
      // Session storage is an optional bridge from the dashboard and sidebar.
    }
    if (!pendingBrief) return;
    let cancelled = false;
    void (async () => {
      // Wait for the thread replay to settle before appending the new brief.
      await copilotkit.connectAgent({ agent });
      if (cancelled) return;
      await startRun(pendingBrief as string);
    })();
    return () => {
      cancelled = true;
    };
  }, [agent, copilotkit, isReady, routeRunId, startRun]);

  const onBuyerStateUpdate = useCallback((next: BuyerState) => {
    setBuyerState((current) => {
      const merged = { ...current, ...next };
      if (next.award && !next.award.winner && current.award?.winner) {
        merged.award = current.award;
      }
      return merged;
    });
  }, []);

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
    events,
    traceError,
    registry,
    registryLoading,
    registryError,
    refreshRegistry,
    onBuyerStateUpdate,
    refreshRun,
  };
}
