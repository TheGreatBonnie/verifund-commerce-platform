import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({ fetchRegistry: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchRegistry: hooks.fetchRegistry }));

import { MessageFromA2A } from "@/features/deal-room/components/a2a/MessageFromA2A";
import { MessageToA2A } from "@/features/deal-room/components/a2a/MessageToA2A";

const NORTHWIND_ID = "33a492070e344199803b6d0f4331cee0";

describe("A2A message card hook order (static flag regression)", () => {
  beforeEach(() => {
    vi.resetModules();
    hooks.fetchRegistry.mockReset();
    hooks.fetchRegistry.mockResolvedValue([
      {
        seller_id: NORTHWIND_ID,
        name: "Northwind Audio",
        card_url: `http://127.0.0.1:9200/${NORTHWIND_ID}/.well-known/agent-card.json`,
        categories: ["Audio"],
        card_hash: "hash",
        last_seen_at: "now",
        healthy: true,
        last_error: null,
      },
    ]);
  });

  it("re-renders from null to card when status changes without hook reorder crash", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <MessageToA2A status="inProgress" args={{ agentName: NORTHWIND_ID, task: "RFQ" }} />
    );
    expect(screen.queryByText("Northwind Audio")).not.toBeInTheDocument();

    rerender(
      <MessageToA2A status="complete" args={{ agentName: NORTHWIND_ID, task: "RFQ · 1 MacBook Air" }} />
    );
    expect(await screen.findByText("Northwind Audio")).toBeInTheDocument();
    const staticErrors = errSpy.mock.calls.filter((c) =>
      String(c[0] ?? "").includes("static flag was missing")
    );
    expect(staticErrors).toEqual([]);
    errSpy.mockRestore();
  });

  it("re-renders from null to card when status changes without hook reorder crash (from)", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <MessageFromA2A status="inProgress" args={{ agentName: NORTHWIND_ID }} response="r" />
    );
    expect(screen.queryByText("Northwind Audio")).not.toBeInTheDocument();

    rerender(
      <MessageFromA2A status="complete" args={{ agentName: NORTHWIND_ID }} response="Response received" />
    );
    expect(await screen.findByText("Northwind Audio")).toBeInTheDocument();
    const staticErrors = errSpy.mock.calls.filter((c) =>
      String(c[0] ?? "").includes("static flag was missing")
    );
    expect(staticErrors).toEqual([]);
    errSpy.mockRestore();
  });
});
