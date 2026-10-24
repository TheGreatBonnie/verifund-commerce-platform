"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchTrace } from "@/lib/api";
import type { TraceEvent } from "@/lib/types";

export function useRunTrace(runId: string, active: boolean, terminal: boolean) {
  return useQuery<TraceEvent[]>({
    queryKey: ["trace", runId],
    queryFn: async () => fetchTrace(runId, 0),
    enabled: active && !!runId,
    refetchInterval: terminal ? false : 1_000,
    select: (data) => [...data].sort((a, b) => a.seq - b.seq),
  });
}
