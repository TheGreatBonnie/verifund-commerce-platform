"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  Heart,
  MessageCircle,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { products } from "@/lib/data";

type SortOrder = "Recommended" | "Price: low to high" | "Price: high to low";

export default function MarketplacePage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All products");
  const [sort, setSort] = useState<SortOrder>("Recommended");
  const [highlyRatedOnly, setHighlyRatedOnly] = useState(false);

  const categories = useMemo(
    () => [...new Set(products.map((product) => product.category))],
    [],
  );
  const visibleProducts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return products
      .filter((product) => {
        const matchesCategory = category === "All products" || product.category === category;
        const matchesQuery = `${product.name} ${product.seller} ${product.desc}`
          .toLowerCase()
          .includes(normalizedQuery);
        const matchesRating = !highlyRatedOnly || Number(product.rating) >= 4.8;
        return matchesCategory && matchesQuery && matchesRating;
      })
      .sort((first, second) => {
        if (sort === "Price: low to high") return first.price - second.price;
        if (sort === "Price: high to low") return second.price - first.price;
        return 0;
      });
  }, [category, highlyRatedOnly, query, sort]);

  const startProductRun = (product: (typeof products)[number]) => {
    const brief = [
      `Find and negotiate the best terms for ${product.name}.`,
      `Product details: ${product.desc}.`,
      `Use the listed price of $${product.price.toLocaleString("en-US")} as my target budget.`,
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
        <span>Prices shown in USD</span>
      </div>

      {visibleProducts.length ? (
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
  product: (typeof products)[number];
  onAskAgent: () => void;
}) {
  const [saved, setSaved] = useState(false);

  return (
    <article className="mm-product-card mm-marketplace-product-card">
      <div
        className="mm-product-art mm-marketplace-product-art"
        style={{ backgroundColor: product.color }}
      >
        <span aria-hidden="true">{product.emoji}</span>
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
        <p className="mm-product-description">{product.desc}</p>
        <div className="mm-product-price">
          <strong>${product.price.toLocaleString("en-US")}</strong>
          <del>${product.original.toLocaleString("en-US")}</del>
        </div>
        <div className="mm-product-meta">
          <span className="mm-marketplace-rating">
            <Star size={12} aria-hidden="true" fill="currentColor" />
            {product.rating} <span>({product.reviews})</span>
          </span>
          <span>{product.seller}</span>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mm-product-action mm-marketplace-product-action mm-button-signal"
          onClick={onAskAgent}
          leftIcon={<MessageCircle size={13} aria-hidden="true" />}
        >
          Ask agent to negotiate
          <ArrowUpRight size={12} aria-hidden="true" />
        </Button>
      </div>
    </article>
  );
}
