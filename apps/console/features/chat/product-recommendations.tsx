"use client";

import { Star } from "lucide-react";
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

export function ProductRecommendations({ status, result }: Props) {
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
    </section>
  );
}
