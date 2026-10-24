"use client";

import { RefreshCw, Radio } from "lucide-react";

import type { RegistrySeller } from "@/lib/types";
import { formatDateTime, shortId } from "@/lib/format";

type RegistryPanelProps = {
  sellers: RegistrySeller[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
};

export function RegistryPanel({
  sellers,
  loading,
  error,
  onRefresh,
}: RegistryPanelProps) {
  return (
    <section className="mm-panel mm-registry" aria-labelledby="registry-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Agent Card index</p>
          <h2 id="registry-title">Registry</h2>
        </div>
        <button
          type="button"
          className="mm-icon-button"
          onClick={onRefresh}
          aria-label="Refresh registry"
          disabled={loading}
        >
          <RefreshCw size={14} aria-hidden="true" className={loading ? "is-spinning" : ""} />
        </button>
      </header>

      {error ? (
        <div className="mm-registry-error">
          <p>{error}</p>
          <button type="button" className="mm-text-button" onClick={onRefresh}>
            Retry
          </button>
        </div>
      ) : sellers.length === 0 ? (
        <p className="mm-empty">
          {loading ? "Reading Agent Cards…" : "No sellers indexed yet."}
        </p>
      ) : (
        <ul className="mm-registry-list">
          {sellers.map((seller) => {
            const card = seller.card_json;
            const extension = card?.capabilities?.extensions?.find((item) =>
              item.uri?.includes("/commerce/"),
            );
            const protocol =
              card?.supportedInterfaces?.find((item) => item.protocolVersion)
                ?.protocolVersion ?? "1.0";
            return (
              <li key={seller.seller_id}>
                <div className="mm-registry-identity">
                  <span
                    className={`mm-health-dot ${seller.healthy ? "is-live" : "is-down"}`}
                    aria-label={seller.healthy ? "Healthy" : "Unhealthy"}
                  />
                  <div>
                    <strong>{seller.name}</strong>
                    <span>{seller.seller_id}</span>
                  </div>
                </div>
                <dl className="mm-registry-facts">
                  <div>
                    <dt>Protocol</dt>
                    <dd>A2A {protocol}</dd>
                  </div>
                  <div>
                    <dt>Streaming</dt>
                    <dd>{card?.capabilities?.streaming ? "Yes" : "No"}</dd>
                  </div>
                  <div>
                    <dt>Commerce ext.</dt>
                    <dd>{extension ? shortId(extension.uri, 24) : "—"}</dd>
                  </div>
                  <div>
                    <dt>Last seen</dt>
                    <dd>{formatDateTime(seller.last_seen_at)}</dd>
                  </div>
                </dl>
                <p className="mm-mono-note mm-registry-card-url">
                  <Radio size={11} aria-hidden="true" /> {seller.card_url}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
