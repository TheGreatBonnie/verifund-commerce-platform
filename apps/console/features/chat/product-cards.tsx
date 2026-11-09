"use client";

import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Handshake, Star } from "lucide-react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import { Button } from "@/components/ui/button";
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
  image_url?: string;
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

function badgeLabel(product: SearchProduct): string | null {
  const available = (product.offers ?? []).filter((offer) => offer.available);
  return available.length ? "In stock" : null;
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
    <li className="mm-product-card mm-product-search-card">
      <div className="mm-product-art mm-product-search-art" aria-hidden="true">
        {product.image_url ? <img src={product.image_url} alt={product.name ?? ""} /> : null}
        {badgeLabel(product) ? <small>{badgeLabel(product)}</small> : null}
      </div>

      <div className="mm-product-info">
        {product.category ? (
          <p className="mm-product-category">{product.category}</p>
        ) : null}
        <h3>{product.name ?? product.sku}</h3>
        {product.description ? (
          <p className="mm-product-description">{product.description}</p>
        ) : null}
        <div className="mm-product-price">
          <strong>{price}</strong>
          {product.original_unit_price_cents ? <del>{original}</del> : null}
        </div>
        <div className="mm-product-meta">
          {typeof product.rating === "number" ? (
            <span className="mm-marketplace-rating">
              <Star size={12} aria-hidden="true" fill="currentColor" />
              {product.rating.toFixed(1)}{" "}
              <span>({product.reviews || "new"})</span>
            </span>
          ) : null}
          <span>{availability(product)}</span>
          <span>{sellerName(product)}</span>
        </div>
        <div className="mm-product-search-action">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mm-product-action mm-button-signal"
            onClick={() => onNegotiate(product)}
            disabled={disabled}
            leftIcon={<Handshake size={13} aria-hidden="true" />}
          >
            Ask agent to negotiate
          </Button>
        </div>
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
  const trackRef = useRef<HTMLUListElement>(null);

  const scrollTrack = (direction: 1 | -1) => {
    trackRef.current?.scrollBy({ left: direction * 288, behavior: "smooth" });
  };

  return (
    <div className="mm-product-search">
      <div className="mm-product-search-head">
        <p className="mm-product-count">
          {total > products.length
            ? `Showing ${products.length} of ${total} matches`
            : `${products.length} ${
                products.length === 1 ? "match" : "matches"
              }`}
        </p>
        {products.length > 1 ? (
          <div className="mm-product-search-nav">
            <button
              type="button"
              className="mm-product-search-nav-button"
              aria-label="Previous products"
              onClick={() => scrollTrack(-1)}
            >
              <ChevronLeft size={15} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="mm-product-search-nav-button"
              aria-label="Next products"
              onClick={() => scrollTrack(1)}
            >
              <ChevronRight size={15} aria-hidden="true" />
            </button>
          </div>
        ) : null}
      </div>
      <ul
        ref={trackRef}
        className="mm-product-grid"
        tabIndex={0}
        aria-label="Recommended products"
      >
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
