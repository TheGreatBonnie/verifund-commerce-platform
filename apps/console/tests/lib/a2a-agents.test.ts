import { describe, expect, it } from "vitest";
import {
  agentBaseUrlFromCardUrl,
  isSellerAgentUrl,
  normalizeAgentBaseUrl,
  registrySellerAgents,
} from "@/lib/a2a-agents";

describe("a2a-agents", () => {
  it("normalizes trailing slashes", () => {
    expect(
      normalizeAgentBaseUrl("https://gateway.onrender.com/sellers/"),
    ).toBe("https://gateway.onrender.com/sellers");
  });

  it("derives the agent base URL from a published card URL", () => {
    expect(
      agentBaseUrlFromCardUrl(
        "https://gw.example.com/sellers/northwind-audio/.well-known/agent-card.json",
      ),
    ).toBe("https://gw.example.com/sellers/northwind-audio");
  });

  it("rejects a URL that is not an agent card", () => {
    expect(agentBaseUrlFromCardUrl("https://gw.example.com/sellers/x")).toBeNull();
    expect(agentBaseUrlFromCardUrl("")).toBeNull();
  });

  it("maps registry sellers to agent base URLs and display names", () => {
    expect(
      registrySellerAgents([
        {
          seller_id: "northwind-audio",
          name: "Northwind Audio",
          card_url:
            "https://gw.example.com/sellers/northwind-audio/.well-known/agent-card.json",
        },
      ]),
    ).toEqual([
      {
        url: "https://gw.example.com/sellers/northwind-audio",
        name: "Northwind Audio",
      },
    ]);
  });

  it("ignores a seller that published no card URL", () => {
    expect(
      registrySellerAgents([{ seller_id: "s1", name: "Seller One" }]),
    ).toEqual([]);
  });

  it("returns nothing when the registry lists no sellers", () => {
    expect(registrySellerAgents([])).toEqual([]);
  });

  it("matches sellers by path prefix when services share one origin", () => {
    const shared = "https://gateway.onrender.com/sellers";
    expect(
      isSellerAgentUrl(
        "https://gateway.onrender.com/sellers/northwind-audio/a2a",
        shared,
      ),
    ).toBe(true);
    expect(
      isSellerAgentUrl("https://gateway.onrender.com/buyer/a2a", shared),
    ).toBe(false);
  });

  it("keeps port matching for the legacy local stack", () => {
    expect(
      isSellerAgentUrl(
        "http://127.0.0.1:9200/northwind-audio/a2a",
        "http://127.0.0.1:9200",
      ),
    ).toBe(true);
    expect(
      isSellerAgentUrl("http://127.0.0.1:9100/a2a", "http://127.0.0.1:9200"),
    ).toBe(false);
  });
});
