import { describe, expect, it } from "vitest";
import {
  isPausedStage,
  isTerminalStage,
  stageLabel,
} from "./stages";

describe("settlement stages", () => {
  it("labels buyer and settlement stages", () => {
    expect(stageLabel("funding_pending")).toBe("Funding pending");
    expect(stageLabel("verification_pending")).toBe(
      "Verification pending",
    );
    expect(stageLabel("review_required")).toBe("Review required");
    expect(stageLabel("released")).toBe("Released");
    expect(stageLabel("ordered")).toBe("Ordered");
  });

  it("treats released and canceled as terminal in settlement mode", () => {
    expect(isTerminalStage("released", true)).toBe(true);
    expect(isTerminalStage("canceled", true)).toBe(true);
    expect(isTerminalStage("failed", true)).toBe(true);
    expect(isTerminalStage("verification_pending", true)).toBe(false);
    expect(isTerminalStage("review_required", true)).toBe(false);
  });

  it("keeps ordered terminal only in legacy mode", () => {
    expect(isTerminalStage("ordered", false)).toBe(true);
    expect(isTerminalStage("ordered", true)).toBe(false);
  });

  it("marks human and provider pauses", () => {
    expect(isPausedStage("awaiting_approval")).toBe(true);
    expect(isPausedStage("funding_pending")).toBe(true);
    expect(isPausedStage("release_permitted")).toBe(true);
    expect(isPausedStage("review_required")).toBe(true);
    expect(isPausedStage("funded")).toBe(false);
    expect(isPausedStage("released")).toBe(false);
  });
});
