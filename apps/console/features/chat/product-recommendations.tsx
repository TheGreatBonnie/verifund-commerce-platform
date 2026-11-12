"use client";

import { useState } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import { Handshake, Star } from "lucide-react";
import { parseVerifundToolResult } from "./verifund-tools";

type RecommendationOffer = {
  seller_name?: string;
  unit_price_cents?: number;
  currency?: string;
  available?: boolean;
};

type RecommendationProduct = {
  sku?: string;
  name?: string;
  best_price_cents?: number;
  currency?: string;
  seller_name?: string;
  seller?: string;
  notes?: string;
  rating?: number;
  image_url?: string;
  offers?: RecommendationOffer[];
  match_rationale?: string[];
};

type RecommendationRef = {
  sku?: string;
  reason?: string;
};

type RecommendationsPayload = {
  title?: string;
  context_note?: string;
  max_unit_price_cents?: number;
  products?: RecommendationProduct[];
  recommendation?: RecommendationRef;
  alternative?: RecommendationRef;
  total_candidates?: number;
  error?: string;
  message?: string;
};

type Props = {
  status?: string;
  result?: unknown;
};

function formatMoney(cents?: number, currency = "USD") {
  if (typeof cents !== "number") return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  } catch {
    return `${currency} ${(cents / 100).toFixed(2)}`;
  }
}

function sellerName(product: RecommendationProduct) {
  return (
    product.seller_name ??
    product.seller ??
    product.offers?.find((o) => o.seller_name)?.seller_name ??
    "—"
  );
}

function notesFor(product: RecommendationProduct) {
  if (product.notes) return product.notes;
  if (typeof product.rating === "number") return `${product.rating.toFixed(1)}★`;
  if (product.match_rationale?.length) return product.match_rationale.join(", ");
  return "—";
}

let fallbackId = 0;
function messageId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  fallbackId += 1;
  return `recommendation-negotiate-${Date.now()}-${fallbackId}`;
}

function negotiateIntent(product: RecommendationProduct) {
  const currency = product.currency ?? product.offers?.[0]?.currency ?? "USD";
  const offers = (product.offers ?? [])
    .map((offer) => {
      const name = offer.seller_name ?? "seller";
      const stock = offer.available === false ? "unavailable" : "available";
      return `${name} ${stock} at ${formatMoney(
        offer.unit_price_cents,
        offer.currency ?? currency,
      )}`;
    })
    .join("; ");
  return [
    "Ask the MarketMesh Buyer to negotiate for this product.",
    `SKU: ${product.sku ?? "unknown"}.`,
    `Name: ${product.name ?? "unknown"}.`,
    `Best price: ${formatMoney(product.best_price_cents, currency)} from ${sellerName(product)}.`,
    offers ? `Offers: ${offers}.` : "Offers: none listed.",
    "Please clarify the mandate (quantity, budget ceiling, delivery deadline, warranty and returns, must-haves) and start sourcing.",
    "Do not place an order.",
  ].join(" ");
}

export function ProductRecommendations({ status, result }: Props) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { copilotkit } = useCopilotKit();
  const [isDispatching, setIsDispatching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = parseVerifundToolResult(result) as RecommendationsPayload | null;

  if (!parsed && (status === "inProgress" || status === "executing")) {
    return (
      <div className="mm-chat-approval-pending" role="status">
        Preparing comparison…
      </div>
    );
  }
  if (!parsed) return null;

  if (parsed.error) {
    return (
      <div className="mm-chat-approval-result" role="alert">
        {parsed.message ?? "Unable to show recommendations."}
      </div>
    );
  }

  const products = Array.isArray(parsed.products) ? parsed.products : [];
  if (!products.length) {
    return (
      <div className="mm-chat-approval-result">
        No matching products to compare.
      </div>
    );
  }

  const recSku = parsed.recommendation?.sku;
  const altSku = parsed.alternative?.sku;

  const negotiate = async (product: RecommendationProduct) => {
    if (isDispatching) return;
    setIsDispatching(true);
    setError(null);
    try {
      agent.addMessage({
        id: messageId(),
        role: "user",
        content: negotiateIntent(product),
      });
      await copilotkit.runAgent({ agent });
    } catch (dispatchError) {
      setError(
        dispatchError instanceof Error
          ? dispatchError.message
          : "Could not ask the agent to negotiate.",
      );
    } finally {
      setIsDispatching(false);
    }
  };

  return (
    <section className="mm-product-recommendations" aria-label="Product comparison">
      {parsed.title ? <h3 className="mm-recommendations-title">{parsed.title}</h3> : null}
      {parsed.context_note ? (
        <p className="mm-recommendations-context">{parsed.context_note}</p>
      ) : null}

      <div className="mm-recommendations-table-wrap">
        <table className="mm-recommendations-table">
          <caption className="sr-only">Results comparison</caption>
          <thead>
            <tr>
              <th scope="col">Laptop</th>
              <th scope="col">Best price</th>
              <th scope="col">Seller</th>
              <th scope="col">Notes</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            {products.map((product, index) => {
              const isRec = recSku && product.sku === recSku;
              const isAlt = altSku && product.sku === altSku;
              return (
                <tr
                  key={product.sku ?? `${product.name ?? "product"}-${index}`}
                  data-recommended={isRec ? "true" : undefined}
                  data-alternative={isAlt ? "true" : undefined}
                >
                  <th scope="row" className="mm-recommendations-name">
                    <span>{product.name ?? product.sku ?? "Unknown product"}</span>
                    {isRec ? <span className="mm-recommendation-badge">Recommended</span> : null}
                    {isAlt ? <span className="mm-recommendation-badge is-alt">Alternative</span> : null}
                  </th>
                  <td className="mm-numeric">
                    {formatMoney(product.best_price_cents, product.currency ?? "USD")}
                  </td>
                  <td>{sellerName(product)}</td>
                  <td className="mm-recommendations-notes">
                    {typeof product.rating === "number" && !product.notes ? (
                      <span className="mm-marketplace-rating">
                        <Star size={12} aria-hidden="true" fill="currentColor" /> {product.rating.toFixed(1)}
                      </span>
                    ) : (
                      notesFor(product)
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="mm-button mm-button-signal mm-recommendations-action"
                      onClick={() => negotiate(product)}
                      disabled={isDispatching}
                      aria-label={`Ask agent to negotiate for ${product.name ?? product.sku ?? "this product"}`}
                    >
                      <Handshake size={13} aria-hidden="true" /> Negotiate
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {parsed.recommendation?.reason ? (
        <p className="mm-recommendation-callout">
          <strong>Recommendation:</strong> {parsed.recommendation.reason}
        </p>
      ) : null}
      {parsed.alternative?.reason ? (
        <p className="mm-recommendation-callout is-alt">
          <strong>Alternative:</strong> {parsed.alternative.reason}
        </p>
      ) : null}
      {error ? (
        <p className="mm-chat-approval-result" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
