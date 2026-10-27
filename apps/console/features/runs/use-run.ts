"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRun } from "@/lib/api";

const TERMINAL = new Set(["ordered", "rejected", "failed", "order_failed", "no_award"]);

export function useRun(runId: string) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["run", runId],
    queryFn: () => fetchRun(runId),
    enabled: !!runId,
    refetchInterval: (query) => {
      const stage = query.state.data?.stage;
      return stage && TERMINAL.has(stage) ? false : 2_000;
    },
  });
  return {
    run: q.data ?? null,
    isLoading: q.isLoading,
    error: q.error ? "Run unavailable" : null,
    refresh: () => qc.invalidateQueries({ queryKey: ["run", runId] }),
  };
}
