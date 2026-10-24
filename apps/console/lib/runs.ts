import type { BuyerState } from "./types";

export function parseBuyerStateFromMessages(
  messages: Array<{ role?: string; content?: unknown }>,
): BuyerState | null {
  let latest: BuyerState | null = null;
  for (const m of messages ?? []) {
    const content = typeof m.content === "string" ? m.content : "";
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(content);
    } catch {
      continue;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) continue;
    let candidate = parsed as BuyerState;
    const taskText = (
      parsed as { status?: { message?: { parts?: Array<{ text?: string }> } } }
    )?.status?.message?.parts?.[0]?.text;
    if (typeof taskText === "string") {
      try {
        const nested = JSON.parse(taskText);
        if (nested && typeof nested === "object" && !Array.isArray(nested)) {
          candidate = nested as BuyerState;
        }
      } catch {
        // keep candidate as parsed
      }
    }
    if (candidate && (candidate.task_id || candidate.award || candidate.mandate || candidate.order)) {
      latest = candidate;
    }
  }
  return latest;
}
