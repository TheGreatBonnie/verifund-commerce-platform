import type { RegistrySeller, TraceEvent } from "./types";

export async function fetchTrace(
  runId: string,
  afterSeq = 0,
): Promise<TraceEvent[]> {
  const response = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/trace?after_seq=${afterSeq}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Trace request failed (${response.status})`);
  }
  return (await response.json()) as TraceEvent[];
}

export async function fetchRegistry(): Promise<RegistrySeller[]> {
  const response = await fetch("/api/registry/sellers", {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Registry request failed (${response.status})`);
  }
  const body = (await response.json()) as { sellers?: RegistrySeller[] };
  return body.sellers ?? [];
}
