"use client";

import { useState } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import { parseVerifundToolResult } from "./verifund-tools";

type ProductOffer = {
  seller_id?: string;
  seller_name?: string;
  unit_price_cents?: number;
  currency?: string;
  available?: boolean;
  on_hand?: number;
  incoming?: number;
};

type SearchProduct = {
  id?: string;
  sku?: string;
  name?: string;
  category?: string;
  description?: string;
  image_emoji?: string;
  color?: string;
  unit_price_cents?: number;
  original_unit_price_cents?: number | null;
  currency?: string;
  rating?: number;
  reviews?: string;
  seller?: string;
  offers?: ProductOffer[];
  match_rationale?: string[];
};

type SearchPayload = {
  products?: SearchProduct[];
  total_candidates?: number;
  error?: string;
  message?: string;
};

type ProductSearchCardsProps = {
  status?: string;
  result?: unknown;
};

function offerCurrency(product: SearchProduct): string {
  return product.currency ?? product.offers?.[0]?.currency ?? "USD";
}

function formatPrice(cents?: number, currency = "USD"): string {
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

function sellerName(product: SearchProduct): string {
  return (
    product.seller ??
    product.offers?.find((offer) => offer.seller_name)?.seller_name ??
    product.offers?.[0]?.seller_name ??
    "MarketMesh seller"
  );
}

function availability(product: SearchProduct): string {
  const available = (product.offers ?? []).filter((offer) => offer.available);
  if (!available.length) return "Out of stock";
  return `In stock at ${available.length} ${
    available.length === 1 ? "seller" : "sellers"
  }`;
}

function negotiateIntent(product: SearchProduct): string {
  const currency = offerCurrency(product);
  const offers = (product.offers ?? [])
    .map((offer) => {
      const name = offer.seller_name ?? offer.seller_id ?? "seller";
      const stock = offer.available ? "in stock" : "unavailable";
      return `${name} ${stock} at ${formatPrice(
        offer.unit_price_cents,
        offer.currency ?? currency,
      )}`;
    })
    .join("; ");
  return [
    "Ask the MarketMesh Buyer to negotiate for this product.",
    `SKU: ${product.sku ?? "unknown"}.`,
    `Name: ${product.name ?? "unknown"}.`,
    `Unit price: ${formatPrice(product.unit_price_cents, currency)}.`,
    `Offers: ${offers || "none listed"}.`,
    "Please clarify the mandate (quantity, budget ceiling, delivery deadline, warranty and returns, must-haves) and start sourcing.",
    "Do not place an order.",
  ].join(" ");
}

let fallbackMessageId = 0;

function messageId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  fallbackMessageId += 1;
  return `product-negotiate-${Date.now()}-${fallbackMessageId}`;
}

function ProductCard({
  product,
  disabled,
  onNegotiate,
}: {
  product: SearchProduct;
  disabled: boolean;
  onNegotiate: (product: SearchProduct) => void;
}) {
  const currency = offerCurrency(product);
  const price = formatPrice(product.unit_price_cents, currency);
  const original = formatPrice(
    product.original_unit_price_cents ?? undefined,
    currency,
  );
  const offers = product.offers ?? [];

  return (
    <li className="mm-product-card">
      <div className="mm-product-card-head">
        <span className="mm-product-emoji" aria-hidden="true">
          {product.image_emoji ?? "📦"}
        </span>
        <div>
          <p className="mm-product-name">{product.name ?? product.sku}</p>
          <p className="mm-product-seller">{sellerName(product)}</p>
        </div>
        <div className="mm-product-price">
          <strong>{price}</strong>
          {product.original_unit_price_cents ? (
            <span className="mm-product-was">{original}</span>
          ) : null}
        </div>
      </div>

      <div className="mm-product-meta">
        <span>{availability(product)}</span>
        {product.category ? <span>{product.category}</span> : null}
        {typeof product.rating === "number" ? (
          <span>
            {product.rating.toFixed(1)} ★
            {product.reviews ? ` · ${product.reviews}` : ""}
          </span>
        ) : null}
      </div>

      {product.description ? (
        <p className="mm-product-description">{product.description}</p>
      ) : null}

      <div className="mm-product-actions">
        <button
          type="button"
          className="mm-product-negotiate"
          onClick={() => onNegotiate(product)}
          disabled={disabled}
        >
          Ask agent to negotiate
        </button>
        <details className="mm-product-details">
          <summary>View details</summary>
          <ul>
            {offers.map((offer, index) => (
              <li key={`${offer.seller_id ?? "seller"}-${index}`}>
                {offer.seller_name ?? offer.seller_id ?? "Seller"} ·{" "}
                {formatPrice(
                  offer.unit_price_cents,
                  offer.currency ?? currency,
                )}{" "}
                · {offer.available ? "available" : "unavailable"}
                {typeof offer.on_hand === "number"
                  ? ` · ${offer.on_hand} on hand`
                  : ""}
              </li>
            ))}
          </ul>
          {product.match_rationale?.length ? (
            <p className="mm-product-rationale">
              Matched: {product.match_rationale.join(", ")}
            </p>
          ) : null}
        </details>
      </div>
    </li>
  );
}

export function ProductSearchCards({
  status,
  result,
}: ProductSearchCardsProps) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { copilotkit } = useCopilotKit();
  const [isDispatching, setIsDispatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = parseVerifundToolResult(result) as SearchPayload | null;

  if (!parsed && (status === "inProgress" || status === "executing")) {
    return (
      <div className="mm-chat-approval-pending" role="status">
        Searching Marketplace…
      </div>
    );
  }
  if (!parsed) return null;

  if (parsed.error) {
    return (
      <div className="mm-chat-approval-result" role="alert">
        {parsed.message ?? "Marketplace catalog is unavailable."}
      </div>
    );
  }

  const products = Array.isArray(parsed.products) ? parsed.products : [];
  if (!products.length) {
    return (
      <div className="mm-chat-approval-result">
        No matching products. Try a broader search or a different budget.
      </div>
    );
  }

  const negotiate = async (product: SearchProduct) => {
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

  const total = parsed.total_candidates ?? products.length;

  return (
    <div className="mm-product-search">
      <p className="mm-product-count">
        {total > products.length
          ? `Showing ${products.length} of ${total} matches`
          : `${products.length} ${
              products.length === 1 ? "match" : "matches"
            }`}
      </p>
      <ul className="mm-product-grid">
        {products.map((product, index) => (
          <ProductCard
            key={product.sku ?? product.id ?? index}
            product={product}
            disabled={isDispatching}
            onNegotiate={(value) => void negotiate(value)}
          />
        ))}
      </ul>
      {error ? (
        <p className="mm-product-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
