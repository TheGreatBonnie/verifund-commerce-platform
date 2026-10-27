/**
 * Agent styling utilities for consistent badge appearance.
 * MarketMesh agents use distinct colors per role.
 */

export type AgentStyle = {
  bgColor: string;
  textColor: string;
  borderColor: string;
  icon: string;
  framework?: string;
};

export function getAgentStyle(agentName: string): AgentStyle {
  if (!agentName) {
    return {
      bgColor: "bg-gray-100",
      textColor: "text-gray-700",
      borderColor: "border-gray-300",
      icon: "🤖",
      framework: "",
    };
  }

  const nameLower = agentName.toLowerCase();

  // MarketMesh Buyer (purple/indigo)
  if (nameLower.includes("buyer") || nameLower.includes("marketmesh")) {
    return {
      bgColor: "bg-gradient-to-r from-indigo-100 to-purple-100",
      textColor: "text-indigo-800",
      borderColor: "border-indigo-400",
      icon: "🛒",
      framework: "MarketMesh",
    };
  }

  // Northwind Audio (blue)
  if (nameLower.includes("northwind")) {
    return {
      bgColor: "bg-gradient-to-r from-blue-100 to-cyan-100",
      textColor: "text-blue-800",
      borderColor: "border-blue-400",
      icon: "🎵",
      framework: "Seller",
    };
  }

  // CircuitForge (amber/orange)
  if (nameLower.includes("circuitforge") || nameLower.includes("circuit")) {
    return {
      bgColor: "bg-gradient-to-r from-amber-100 to-orange-100",
      textColor: "text-amber-800",
      borderColor: "border-amber-400",
      icon: "🔧",
      framework: "Seller",
    };
  }

  // Aurora Supply (pink/rose)
  if (nameLower.includes("aurora")) {
    return {
      bgColor: "bg-gradient-to-r from-pink-100 to-rose-100",
      textColor: "text-pink-800",
      borderColor: "border-pink-400",
      icon: "🌅",
      framework: "Seller",
    };
  }

  // Summit Tech Supply (green)
  if (nameLower.includes("summit tech") || nameLower.includes("summit-tech")) {
    return {
      bgColor: "bg-gradient-to-r from-emerald-100 to-teal-100",
      textColor: "text-emerald-800",
      borderColor: "border-emerald-400",
      icon: "⛰️",
      framework: "Seller",
    };
  }

  // Default
  return {
    bgColor: "bg-gray-100",
    textColor: "text-gray-700",
    borderColor: "border-gray-300",
    icon: "🤖",
    framework: "",
  };
}

export function truncateTask(text: string, maxLength: number = 50): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength) + "…";
}
