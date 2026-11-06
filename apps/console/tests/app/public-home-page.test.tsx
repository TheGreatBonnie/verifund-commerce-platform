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
      image_emoji: "🎧",
      tag: "Available",
      color: "#eef2ed",
      unit_price_cents: 29900,
      original_unit_price_cents: 34900,
      rating: 4.8,
      reviews: 128,
      seller: "Northwind Audio",
      offers: [],
    },
  ]),
}));

const useRuns = vi.hoisted(() =>
  vi.fn(() => ({ runs: [], isLoading: false, error: null, refresh: vi.fn() })),
);
vi.mock("@/features/runs/use-runs", () => ({ useRuns }));

vi.mock("@/features/runs/run-summary-card", () => ({
  RunSummaryCard: () => <div data-testid="run-summary" />,
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
    useRuns.mockClear();
  });

  it("hides recent activity and disables the runs query for signed-out visitors", async () => {
    renderHome();
    expect(await screen.findByText("Nimbus NC-700")).toBeInTheDocument();
    expect(screen.queryByText("Recent activity")).not.toBeInTheDocument();
    expect(useRuns).toHaveBeenCalledWith({ enabled: false });
  });

  it("shows recent activity and enables the runs query for signed-in visitors", async () => {
    clerk.isSignedIn = true;
    renderHome();
    expect(await screen.findByText("Recent activity")).toBeInTheDocument();
    expect(useRuns).toHaveBeenCalledWith({ enabled: true });
  });
});
