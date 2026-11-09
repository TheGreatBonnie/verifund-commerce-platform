export const money = (cents: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(cents / 100);

export const moneyParts = (cents: number) => {
  const formatted = money(cents);
  return { whole: formatted.slice(0, -3), cents: formatted.slice(-3) };
};

export const signedMoney = (cents: number) =>
  `${cents >= 0 ? "−" : "+"}${money(Math.abs(cents))}`;

export const formatDateTime = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
};

export const formatTime = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
};

export const formatDate = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
};

export const shortId = (value?: string | null, length = 10) => {
  if (!value) return "—";
  return value.length > length ? `${value.slice(0, length)}…` : value;
};

export const scoreLabel = (score?: number) =>
  typeof score === "number" ? score.toFixed(1) : "—";

export const unitPrice = (offer?: { line_items?: { unit_price_cents: number; warranty_addon_cents: number }[] } | null) => {
  const line = offer?.line_items?.[0];
  return line ? line.unit_price_cents + (line.warranty_addon_cents ?? 0) : 0;
};

export const offerExpiry = (validUntil?: string) => {
  if (!validUntil) return "Expiry unknown";
  const expiry = new Date(validUntil).getTime();
  if (Number.isNaN(expiry)) return "Expiry unknown";
  const remaining = expiry - Date.now();
  if (remaining <= 0) return "Offer expired";
  const minutes = Math.ceil(remaining / 60_000);
  if (minutes < 60) return `Offer expires in ${minutes} min`;
  const hours = Math.ceil(minutes / 60);
  return `Offer expires in ${hours} hr`;
};

export { stageLabel } from "./stages";

export const offerStatus = (status?: string) => {
  const labels: Record<string, string> = {
    proposed: "Proposed",
    final: "Final",
    accepted: "Accepted",
    rejected: "Rejected",
    cancelled: "Cancelled",
    error: "Error",
  };
  return labels[status ?? ""] ?? "Open";
};

/**
 * Derive evidence counts from either shape the console may receive:
 * - legacy `{ required: string[], received: string[] }`
 * - backend `EvidenceSummary { requirements: [{ status, submissions }], items }`
 * Returns `null` when there is nothing to report (null, `{}`, or zero requirements).
 */
export const evidenceCounts = (
  evidence: unknown,
): { required: number; received: number } | null => {
  if (!evidence || typeof evidence !== "object") return null;
  const ev = evidence as Record<string, any>;
  if (Array.isArray(ev.required) && Array.isArray(ev.received)) {
    const required = ev.required.length;
    if (required === 0) return null;
    return { required, received: ev.received.length };
  }
  if (Array.isArray(ev.requirements)) {
    const requirements = ev.requirements as Array<Record<string, any>>;
    const required = requirements.length;
    if (required === 0) return null;
    const received = requirements.filter((r) => {
      if (!r) return false;
      if (typeof r.status === "string") return r.status !== "not_submitted";
      if (Array.isArray(r.submissions)) return r.submissions.length > 0;
      return false;
    }).length;
    return { required, received };
  }
  return null;
};
