import type { BuyerTransactionSummary } from "./buyer-transaction-types";

export const SUPPORTED_FILTER_KEYS = [
  "status",
  "payment_status",
  "fulfillment_status",
  "limit",
] as const;

export type BuyerFilterKey = (typeof SUPPORTED_FILTER_KEYS)[number];

export function filterParamsFromSearch(
  search: { get(key: string): string | null },
): Record<string, string> {
  const params: Record<string, string> = {};
  for (const key of SUPPORTED_FILTER_KEYS) {
    const value = search.get(key);
    if (value) params[key] = value;
  }
  return params;
}

export function deriveFulfillmentCounts(
  items: BuyerTransactionSummary[],
): Record<string, number> {
  const counts: Record<string, number> = {
    awaiting_fulfillment: 0,
    in_progress: 0,
    awaiting_inspection: 0,
    issue: 0,
    completed: 0,
  };

  for (const item of items) {
    const status = item.fulfillment_status ?? item.fulfillment?.status;
    if (!status) continue;
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

export function distinctOptions(values: Array<string | null | undefined>) {
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value === "string" && value.trim()) seen.add(value);
  }
  return [...seen].sort().map((value) => ({
    value,
    label: value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
  }));
}
