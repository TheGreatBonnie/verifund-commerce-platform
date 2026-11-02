"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Handshake,
  Heart,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetchMarketplaceProducts } from "@/lib/api";
import type { MarketplaceProduct } from "@/lib/types";

type SortOrder = "Recommended" | "Price: low to high" | "Price: high to low";

export default function MarketplacePage() {
  const router = useRouter();
  const catalogQuery = useQuery({
    queryKey: ["marketplace-products"],
    queryFn: fetchMarketplaceProducts,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const products = catalogQuery.data ?? [];
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All products");
  const [sort, setSort] = useState<SortOrder>("Recommended");
  const [highlyRatedOnly, setHighlyRatedOnly] = useState(false);

  const categories = useMemo(
    () => [...new Set(products.map((product) => product.category))],
    [products],
  );
  const visibleProducts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return products
      .filter((product) => {
        const matchesCategory = category === "All products" || product.category === category;
        const matchesQuery = `${product.name} ${product.description} ${product.offers.map((offer) => offer.seller_name).join(" ")}`
          .toLowerCase()
          .includes(normalizedQuery);
        const matchesRating = !highlyRatedOnly || Number(product.rating) >= 4.8;
        return matchesCategory && matchesQuery && matchesRating;
      })
      .sort((first, second) => {
        if (sort === "Price: low to high") return first.unit_price_cents - second.unit_price_cents;
        if (sort === "Price: high to low") return second.unit_price_cents - first.unit_price_cents;
        return 0;
      });
  }, [products, category, highlyRatedOnly, query, sort]);

  const startProductRun = (product: MarketplaceProduct) => {
    const brief = [
      `Find and negotiate the best terms for ${product.name}.`,
      `Product SKU: ${product.sku}.`,
      `Product details: ${product.description}.`,
      `Use $${(product.unit_price_cents / 100).toLocaleString("en-US")} per unit as the listed target budget.`,
      `Compare offers from ${product.offers.map((offer) => offer.seller_id).join(", ")}.`,
      "Compare sellers, delivery, warranty, and returns. Do not place an order without my approval.",
    ].join(" ");

    try {
      window.sessionStorage.setItem("marketmesh:pendingBrief", brief);
    } catch {
      // The fresh agent page still opens if session storage is unavailable.
    }
    router.push(`/agents/${crypto.randomUUID()}`);
  };

  return (
    <div className="mm-marketplace-page">
      <header className="mm-marketplace-header">
        <div>
          <p className="mm-kicker">Discover &amp; compare</p>
          <h1>Marketplace</h1>
          <p className="mm-marketplace-description">
            Explore products and let your agents find the best terms.
          </p>
        </div>
        <span className="mm-marketplace-ai-badge">
          <Sparkles size={13} aria-hidden="true" /> AI-assisted shopping
        </span>
      </header>

      <section className="mm-marketplace-toolbar" aria-label="Search and filter products">
        <label className="mm-marketplace-search">
          <Search size={15} aria-hidden="true" />
          <span className="sr-only">Search products, sellers, or features</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search products, sellers, or features…"
          />
        </label>

        <label className="mm-marketplace-select-wrap">
          <span className="sr-only">Category</span>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option>All products</option>
            {categories.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>

        <label className="mm-marketplace-select-wrap">
          <span className="sr-only">Sort products</span>
          <select value={sort} onChange={(event) => setSort(event.target.value as SortOrder)}>
            <option>Recommended</option>
            <option>Price: low to high</option>
            <option>Price: high to low</option>
          </select>
        </label>

        <button
          type="button"
          className={`mm-marketplace-filter${highlyRatedOnly ? " is-active" : ""}`}
          aria-pressed={highlyRatedOnly}
          onClick={() => setHighlyRatedOnly((active) => !active)}
        >
          <SlidersHorizontal size={14} aria-hidden="true" />
          {highlyRatedOnly ? "Rating 4.8+" : "Filters"}
        </button>
      </section>

      <div className="mm-marketplace-results" aria-live="polite">
        <span>Showing <strong>{visibleProducts.length}</strong> products</span>
        <span>Live seller listings · prices shown in USD</span>
      </div>

      {catalogQuery.isLoading ? (
        <div className="mm-marketplace-empty" aria-busy="true">Loading live seller catalogs…</div>
      ) : catalogQuery.error ? (
        <div className="mm-marketplace-empty" role="alert">
          <h2>Marketplace catalog unavailable</h2>
          <p>{catalogQuery.error.message}</p>
          <Button type="button" variant="outline" size="sm" onClick={() => void catalogQuery.refetch()}>Retry</Button>
        </div>
      ) : visibleProducts.length ? (
        <section className="mm-marketplace-grid" aria-label="Marketplace products">
          {visibleProducts.map((product) => (
            <MarketplaceProductCard
              key={product.id}
              product={product}
              onAskAgent={() => startProductRun(product)}
            />
          ))}
        </section>
      ) : (
        <div className="mm-marketplace-empty" role="status">
          <Search size={24} aria-hidden="true" />
          <h2>No products found</h2>
          <p>Try another search or category.</p>
        </div>
      )}
    </div>
  );
}

function MarketplaceProductCard({
  product,
  onAskAgent,
}: {
  product: MarketplaceProduct;
  onAskAgent: () => void;
}) {
  const [saved, setSaved] = useState(false);

  return (
    <article className="mm-product-card mm-marketplace-product-card">
      <div
        className="mm-product-art mm-marketplace-product-art"
        style={{ backgroundColor: product.color }}
      >
        <span aria-hidden="true">{product.image_emoji}</span>
        <small>{product.tag}</small>
        <button
          type="button"
          className={`mm-marketplace-save${saved ? " is-saved" : ""}`}
          aria-label={saved ? `Remove ${product.name} from saved products` : `Save ${product.name}`}
          aria-pressed={saved}
          onClick={() => setSaved((current) => !current)}
        >
          <Heart size={14} aria-hidden="true" fill={saved ? "currentColor" : "none"} />
        </button>
      </div>

      <div className="mm-product-info mm-marketplace-product-info">
        <p className="mm-product-category">{product.category}</p>
        <h2>{product.name}</h2>
        <p className="mm-product-description">{product.description}</p>
        <div className="mm-product-price">
          <strong>${(product.unit_price_cents / 100).toLocaleString("en-US")}</strong>
          {product.original_unit_price_cents ? <del>${(product.original_unit_price_cents / 100).toLocaleString("en-US")}</del> : null}
        </div>
        <div className="mm-product-meta">
          <span className="mm-marketplace-rating">
            <Star size={12} aria-hidden="true" fill="currentColor" />
            {product.rating.toFixed(1)} <span>({product.reviews || "new"})</span>
          </span>
          <span>{product.offers.length} seller{product.offers.length === 1 ? "" : "s"}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="mm-product-action mm-button-signal"
          onClick={onAskAgent}
          leftIcon={<Handshake size={13} aria-hidden="true" />}
        >
          Ask agent to negotiate
        </Button>
      </div>
    </article>
  );
}
