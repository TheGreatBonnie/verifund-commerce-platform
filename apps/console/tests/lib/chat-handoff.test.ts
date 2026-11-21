import { describe, expect, it } from "vitest";

import { buildChatHandoffPrompt } from "@/lib/chat-handoff";

describe("buildChatHandoffPrompt", () => {
  it("builds a release prompt that keeps the human approval gate explicit", () => {
    const prompt = buildChatHandoffPrompt("tx_123", "release");
    expect(prompt).toContain("tx_123");
    expect(prompt).toMatch(/release/i);
    expect(prompt).toMatch(/approv/i);
  });

  it("builds a reject prompt bound to the transaction", () => {
    const prompt = buildChatHandoffPrompt("tx_123", "reject");
    expect(prompt).toContain("tx_123");
    expect(prompt).toMatch(/reject/i);
  });

  it("builds a neutral review prompt for review and unknown intents", () => {
    expect(buildChatHandoffPrompt("tx_123", "review")).toMatch(/review/i);
    expect(buildChatHandoffPrompt("tx_123", "something-else")).toMatch(
      /review/i,
    );
  });

  it("returns null when there is no transaction to bind to", () => {
    expect(buildChatHandoffPrompt("", "release")).toBeNull();
  });
});
