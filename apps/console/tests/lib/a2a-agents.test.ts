import { describe, expect, it } from "vitest";
import {
  isSellerAgentUrl,
  normalizeAgentBaseUrl,
  sellerAgentUrls,
} from "@/lib/a2a-agents";

describe("a2a-agents", () => {
  it("normalizes trailing slashes", () => {
    expect(
      normalizeAgentBaseUrl("https://gateway.onrender.com/sellers/"),
    ).toBe("https://gateway.onrender.com/sellers");
  });

  it("builds seller URLs under a gateway mount prefix", () => {
    expect(sellerAgentUrls("https://gateway.onrender.com/sellers/")).toEqual([
      "https://gateway.onrender.com/sellers/northwind-audio",
      "https://gateway.onrender.com/sellers/circuitforge",
      "https://gateway.onrender.com/sellers/aurora-supply",
      "https://gateway.onrender.com/sellers/summit-tech",
    ]);
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
