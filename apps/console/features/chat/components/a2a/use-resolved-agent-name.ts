"use client";

import { useEffect, useState } from "react";
import { fetchRegistry } from "@/lib/api";

// Process-wide cache: every A2A card shares one registry fetch instead of
// issuing its own. (Tests use vi.resetModules to reset this.)
let namesPromise: Promise<Map<string, string>> | null = null;

function loadSellerNames(): Promise<Map<string, string>> {
  if (!namesPromise) {
    namesPromise = fetchRegistry()
      .then((sellers) => new Map(sellers.map((s) => [s.seller_id, s.name])))
      .catch(() => new Map<string, string>());
  }
  return namesPromise;
}

/**
 * Resolves an agent label to its display name. Thread cards receive the
 * seller's raw seller_id (often a UUID undocumented to the user); the
 * registry maps it to the business name. Known labels (Orchestrator,
 * MarketMesh Buyer, …) are not seller ids, so they pass through unchanged.
 * The card re-renders with the name once the lookup resolves.
 */
export function useResolvedAgentName(
  agentName: string | undefined,
): string | undefined {
  const [resolved, setResolved] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!agentName) return;
    let cancelled = false;
    loadSellerNames().then((names) => {
      if (!cancelled) setResolved(names.get(agentName) ?? agentName);
    });
    return () => {
      cancelled = true;
    };
  }, [agentName]);

  return resolved ?? agentName;
}
