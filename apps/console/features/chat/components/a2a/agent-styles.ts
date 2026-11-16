/**
 * Agent styling utilities for A2A message cards.
 *
 * These describe *roles*, not presentation. The Verifund console owns its
 * palette in globals.css (paper/panel, ink, signal, acid, amber); emitting raw
 * Tailwind color utilities from here let a generic SaaS palette leak into the
 * chat. Map names to a tone and let the CSS theme decide how a tone looks.
 */

export type AgentTone = "buyer" | "verifund" | "seller" | "neutral";

export type AgentStyle = {
  tone: AgentTone;
  glyph: string;
  role: string;
};

export function getAgentStyle(agentName: string): AgentStyle {
  const nameLower = (agentName ?? "").toLowerCase();

  // MarketMesh Buyer
  if (nameLower.includes("buyer") || nameLower.includes("marketmesh")) {
    return { tone: "buyer", glyph: "BUY", role: "MarketMesh" };
  }

  // Verifund settlement agent
  if (nameLower.includes("verifund")) {
    return { tone: "verifund", glyph: "VF", role: "Verifund" };
  }

  // Seller agents (registered by their business names)
  if (
    nameLower.includes("northwind") ||
    nameLower.includes("circuit") ||
    nameLower.includes("aurora") ||
    nameLower.includes("summit tech") ||
    nameLower.includes("summit-tech") ||
    nameLower.includes("seller")
  ) {
    return { tone: "seller", glyph: "SLR", role: "Seller" };
  }

  return { tone: "neutral", glyph: "AGT", role: "" };
}

export function truncateTask(text: string, maxLength: number = 50): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength) + "…";
}
