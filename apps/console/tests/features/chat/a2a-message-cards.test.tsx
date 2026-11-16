import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ fetchRegistry: vi.fn() }));

vi.mock("@/lib/api", () => ({ fetchRegistry: api.fetchRegistry }));

import { getAgentStyle } from "@/features/chat/components/a2a/agent-styles";
import { MessageFromA2A } from "@/features/chat/components/a2a/MessageFromA2A";
import { MessageToA2A } from "@/features/chat/components/a2a/MessageToA2A";

describe("A2A message cards", () => {
  beforeEach(() => {
    api.fetchRegistry.mockReset();
    api.fetchRegistry.mockResolvedValue([]);
  });

  it("describes agents as theme tones instead of Tailwind palette classes", () => {
    expect(getAgentStyle("MarketMesh Buyer")).toEqual({
      tone: "buyer",
      glyph: "BUY",
      role: "MarketMesh",
    });
    expect(getAgentStyle("Verifund")).toEqual({
      tone: "verifund",
      glyph: "VF",
      role: "Verifund",
    });
    expect(getAgentStyle("Northwind Audio")).toEqual({
      tone: "seller",
      glyph: "SLR",
      role: "Seller",
    });
    expect(getAgentStyle("an unknown agent")).toEqual({
      tone: "neutral",
      glyph: "AGT",
      role: "",
    });
  });

  it("renders the outgoing card with console theme classes", async () => {
    await act(async () => {
      render(
        <MessageToA2A
          status="complete"
          args={{ agentName: "Verifund", task: "Fund the agreed order" }}
        />,
      );
    });

    const card = document.querySelector(".mm-a2a-card");
    expect(card).toBeInTheDocument();
    expect(card?.classList).toContain("mm-a2a-card--outgoing");
    expect(card?.className).not.toMatch(
      /bg-(green|blue|indigo|purple|amber|cyan|teal|pink|rose|emerald|orange|gray)-|from-(indigo|blue|amber|cyan|pink|emerald)-/,
    );
    expect(document.querySelector(".mm-a2a-badge--verifund")).toBeInTheDocument();
    expect(screen.getByText("Fund the agreed order")).toBeInTheDocument();
  });

  it("renders the incoming card with a themed status line", async () => {
    await act(async () => {
      render(
        <MessageFromA2A
          status="complete"
          args={{ agentName: "Northwind Audio" }}
          response="Offer accepted"
        />,
      );
    });

    expect(document.querySelector(".mm-a2a-card--incoming")).toBeInTheDocument();
    expect(document.querySelector(".mm-a2a-badge--seller")).toBeInTheDocument();
    expect(document.querySelector(".mm-status")).toHaveTextContent("Offer accepted");
  });
});
