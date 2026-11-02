import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchRun: vi.fn(() => new Promise(() => {})),
}));

import { useRun } from "@/features/runs/use-run";

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

describe("useRun", () => {
  it("keeps the refresh callback stable across renders", () => {
    const { result, rerender } = renderHook(() => useRun("run-1"), {
      wrapper: createWrapper(),
    });
    const firstRefresh = result.current.refresh;

    rerender();

    expect(result.current.refresh).toBe(firstRefresh);
  });
});
