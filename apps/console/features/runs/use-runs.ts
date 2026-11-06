"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRuns } from "@/lib/api";

const TERMINAL = new Set(["ordered", "rejected", "failed", "order_failed", "no_award"]);

export function useRuns({ enabled = true }: { enabled?: boolean } = {}) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["runs"], queryFn: () => fetchRuns(50), staleTime: 5_000, enabled });
  return {
    runs: q.data ?? [],
    isLoading: q.isLoading,
    error: q.error ? "Runs unavailable" : null,
    refresh: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  };
}

export { TERMINAL };
