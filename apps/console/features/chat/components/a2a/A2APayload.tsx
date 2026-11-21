"use client";

export type A2APayloadType =
  | "rfq"
  | "quote"
  | "counter"
  | "agreement"
  | "payment"
  | "fulfillment"
  | "evidence"
  | "verification"
  | "settlement";

export type A2APayloadProps = {
  type?: A2APayloadType;
  data?: Record<string, unknown>;
};

const PAYLOAD_TITLES: Record<A2APayloadType, string> = {
  rfq: "Request for quote",
  quote: "Quotation",
  counter: "Counter offer",
  agreement: "Agreement",
  payment: "Payment",
  fulfillment: "Fulfillment",
  evidence: "Evidence",
  verification: "Verification",
  settlement: "Settlement",
};

export function A2APayload({ type, data }: A2APayloadProps) {
  if (!type) return null;

  const title = PAYLOAD_TITLES[type] ?? "Payload";
  const hasData = data && typeof data === "object" && Object.keys(data).length > 0;

  return (
    <div className="mt-3 rounded-xl bg-slate-50 px-3.5 py-3 border border-slate-100">
      <div className="text-sm font-medium text-slate-800">{title}</div>
      <div className="mt-0.5 text-xs text-slate-500">
        {hasData ? "Structured details available." : "Details unavailable."}
      </div>
    </div>
  );
}
