import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  fetchMarketplaceProducts: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  fetchMarketplaceProducts: mocks.fetchMarketplaceProducts,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

import MarketplacePage from "@/app/(console)/marketplace/page";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

const products = [
  {
    id: "p1",
    sku: "SKU-1",
    name: "Product One",
    category: "Electronics",
    description: "desc",
    image_emoji: "📦",
    color: "#fff",
    original_unit_price_cents: 1000,
    rating: 4.9,
    reviews: "10",
    tag: "Available",
    offers: [
      {
        seller_id: "s1",
        seller_name: "Seller One",
        unit_price_cents: 900,
        currency: "USD",
        available: true,
        on_hand: 5,
        incoming: 0,
      },
    ],
    unit_price_cents: 900,
    seller: "Seller One",
  },
  {
    id: "p2",
    sku: "SKU-2",
    name: "Product Two",
    category: "Home",
    description: "desc2",
    image_emoji: "📦",
    color: "#fff",
    original_unit_price_cents: 2000,
    rating: 4.5,
    reviews: "5",
    tag: "Available",
    offers: [
      {
        seller_id: "s2",
        seller_name: "Seller Two",
        unit_price_cents: 1800,
        currency: "USD",
        available: true,
        on_hand: 3,
        incoming: 0,
      },
    ],
    unit_price_cents: 1800,
    seller: "Seller Two",
  },
];

describe("MarketplacePage", () => {
  beforeEach(() => {
    mocks.fetchMarketplaceProducts.mockReset();
    mocks.fetchMarketplaceProducts.mockResolvedValue(products);
  });

  it("renders products after the catalog resolves", async () => {
    render(<MarketplacePage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByText("Product One")).toBeInTheDocument(),
    );
    expect(screen.getByText("Product Two")).toBeInTheDocument();
    expect(document.querySelectorAll(".mm-marketplace-grid > *").length).toBe(2);
  });
});
