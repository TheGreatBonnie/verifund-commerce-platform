"use client";

import { useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Radio } from "lucide-react";

import type { TraceEvent } from "@/lib/types";
import { formatTime, shortId } from "@/lib/format";

type SellerOption = { seller_id: string; name: string };

type A2AWireProps = {
  events: TraceEvent[];
  sellers: SellerOption[];
  sellerFilter: string;
  onSellerFilterChange: (sellerId: string) => void;
  stage?: string;
  error?: string | null;
};

const TERMINAL_STAGES = new Set([
  "ordered",
  "rejected",
  "failed",
  "order_failed",
  "no_award",
]);

function eventState(event: TraceEvent) {
  const payload = event.payload as Record<string, unknown>;
  const statusUpdate = payload?.statusUpdate as
    | { status?: { state?: string } }
    | undefined;
  const task = payload?.task as
    | { status?: { state?: string } }
    | undefined;
  const artifact = payload?.artifactUpdate as
    | { artifact?: { parts?: Array<{ data?: { kind?: string } }> } }
    | undefined;
  return (
    statusUpdate?.status?.state ??
    task?.status?.state ??
    artifact?.artifact?.parts?.[0]?.data?.kind ??
    (typeof payload?.kind === "string" ? payload.kind : "frame")
  );
}

export function A2AWire({
  events,
  sellers,
  sellerFilter,
  onSellerFilterChange,
  stage,
  error,
}: A2AWireProps) {
  const [direction, setDirection] = useState<"all" | "inbound" | "outbound">(
    "all",
  );

  const visible = useMemo(
    () =>
      events.filter((event) => {
        if (direction !== "all" && event.direction !== direction) return false;
        if (sellerFilter !== "all" && event.seller_id !== sellerFilter) {
          return false;
        }
        return true;
      }),
    [direction, events, sellerFilter],
  );

  const live = !TERMINAL_STAGES.has(stage ?? "");

  return (
    <section id="a2a-wire" className="mm-wire" aria-labelledby="wire-title">
      <header className="mm-wire-head">
        <div className="mm-wire-title">
          <span className={`mm-live-dot ${live ? "is-live" : ""}`} aria-hidden="true" />
          <div>
            <p className="mm-kicker">A2A transport · JSON-RPC 2.0</p>
            <h2 id="wire-title">The wire</h2>
          </div>
        </div>
        <span className="mm-wire-count">
          <Radio size={12} aria-hidden="true" /> {events.length} frames
          {live ? " · live" : " · closed"}
        </span>
      </header>

      <div className="mm-wire-controls">
        <div className="mm-filter-group" role="group" aria-label="Filter by direction">
          {(["all", "inbound", "outbound"] as const).map((item) => (
            <button
              key={item}
              type="button"
              className={direction === item ? "is-active" : ""}
              aria-pressed={direction === item}
              onClick={() => setDirection(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <label className="mm-wire-select">
          <span className="sr-only">Filter by seller</span>
          <select
            value={sellerFilter}
            onChange={(event) => onSellerFilterChange(event.target.value)}
          >
            <option value="all">All sellers</option>
            {sellers.map((seller) => (
              <option key={seller.seller_id} value={seller.seller_id}>
                {seller.name}
              </option>
            ))}
          </select>
        </label>
        {error ? <span className="mm-wire-error">{error}</span> : null}
      </div>

      {visible.length === 0 ? (
        <p className="mm-wire-empty">
          No A2A frames yet. Start a run to see the wire.
        </p>
      ) : (
        <div className="mm-wire-scroll">
          <table>
            <caption className="sr-only">
              A2A transport frames, newest last, with seller, RPC method, task
              identifier, state, latency, and redacted payload.
            </caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Dir</th>
                <th scope="col">Seller</th>
                <th scope="col">Method</th>
                <th scope="col">Task</th>
                <th scope="col">State</th>
                <th scope="col">Latency</th>
                <th scope="col">Frame</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((event) => (
                <tr key={event.id}>
                  <td className="mm-wire-time">{formatTime(event.created_at)}</td>
                  <td>
                    <span
                      className={`mm-direction ${event.direction}`}
                      title={event.direction}
                    >
                      {event.direction === "inbound" ? (
                        <ArrowDownLeft size={13} aria-label="Inbound" />
                      ) : event.direction === "outbound" ? (
                        <ArrowUpRight size={13} aria-label="Outbound" />
                      ) : (
                        "·"
                      )}
                    </span>
                  </td>
                  <td className="mm-wire-seller">
                    {sellers.find((seller) => seller.seller_id === event.seller_id)
                      ?.name ??
                      event.seller_id ??
                      "buyer"}
                  </td>
                  <td className="mm-wire-method">{event.method}</td>
                  <td className="mm-wire-task">{shortId(event.task_id, 8)}</td>
                  <td>
                    <span className="mm-wire-state">{eventState(event)}</span>
                  </td>
                  <td className="mm-numeric">
                    {event.latency_ms != null ? `${event.latency_ms} ms` : "—"}
                  </td>
                  <td>
                    <details className="mm-frame-details">
                      <summary>Inspect</summary>
                      <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
