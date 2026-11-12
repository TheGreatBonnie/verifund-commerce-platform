import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clerk = vi.hoisted(() => ({ isSignedIn: false as boolean | undefined }));

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isSignedIn: clerk.isSignedIn }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  fetchMarketplaceProducts: vi.fn(async () => [
    {
      id: "p1",
      name: "Nimbus NC-700",
      category: "Audio",
      description: "ANC headset",
      image_url: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500",
      tag: "Available",
      unit_price_cents: 29900,
      original_unit_price_cents: 34900,
      rating: 4.8,
      reviews: 128,
      seller: "Northwind Audio",
      offers: [],
    },
  ]),
}));

import Home from "@/app/(public)/page";

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Home />
    </QueryClientProvider>,
  );
}

describe("Home page (public)", () => {
  beforeEach(() => {
    clerk.isSignedIn = false;
  });

  it("hides recent activity for signed-out visitors", async () => {
    renderHome();
    expect(await screen.findByText("Nimbus NC-700")).toBeInTheDocument();
    expect(screen.queryByText("Recent activity")).not.toBeInTheDocument();
  });

  it("shows recent activity and transactions link for signed-in visitors", async () => {
    clerk.isSignedIn = true;
    renderHome();
    expect(await screen.findByText("Recent activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View transactions/i })).toBeInTheDocument();
  });
});
