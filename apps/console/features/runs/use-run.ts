"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRun } from "@/lib/api";
import { isTerminalStage } from "@/lib/stages";

export function useRun(runId: string) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["run", runId],
    queryFn: () => fetchRun(runId),
    enabled: !!runId,
    refetchInterval: (query) => {
      const data = query.state.data;
      // A brand-new thread has no run row yet; stop polling until one exists
      // to avoid hammering /api/runs with 404s.
      if (!data || query.state.status === "error") {
        return false;
      }
      if (isTerminalStage(data?.stage, Boolean(data?.settlement))) {
        return false;
      }
      return data?.stage === "review_required" ? 10_000 : 2_000;
    },
  });
  return {
    run: q.data ?? null,
    isLoading: q.isLoading,
    error: q.error ? "Run unavailable" : null,
    refresh: () => qc.invalidateQueries({ queryKey: ["run", runId] }),
  };
}
