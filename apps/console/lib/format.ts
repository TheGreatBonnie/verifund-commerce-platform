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

export const stageLabel = (stage?: string) => {
  const labels: Record<string, string> = {
    new: "Brief",
    brief_ready: "Brief parsed",
    sellers_discovered: "Sellers discovered",
    sourcing_planned: "RFQ composed",
    negotiating: "Negotiating",
    awaiting_approval: "Awaiting approval",
    approved: "Approved",
    rejected: "Rejected",
    ordering: "Ordering",
    ordered: "Ordered",
    order_failed: "Order failed",
    no_award: "No award",
    failed: "Failed",
    needs_clarification: "Brief needed",
  };
  return labels[stage ?? "new"] ?? "Brief";
};

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
