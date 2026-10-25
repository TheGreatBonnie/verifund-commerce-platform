"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRegistry } from "@/lib/api";

export function useRegistry() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["registry"], queryFn: fetchRegistry, refetchInterval: 15_000 });
  return {
    sellers: q.data ?? [],
    isLoading: q.isLoading,
    isRefreshing: q.isFetching,
    error: q.error ? "Registry offline — Agent Cards unavailable." : null,
    refresh: () => qc.invalidateQueries({ queryKey: ["registry"] }),
  };
}
