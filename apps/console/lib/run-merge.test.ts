import { describe, expect, it } from "vitest";
import type { BuyerRun } from "./api";
import { mergeRunState } from "./run-merge";
import type { BuyerState, SettlementProjection } from "./types";

const settlement = {
  transaction_id: "vf_1",
  state: "FUNDED",
  amount_cents: 123400,
} as SettlementProjection;

describe("mergeRunState", () => {
  it("merges the run projection into the agent state", () => {
    const state: BuyerState = {
      run_id: "run-1",
      stage: "approved",
      settlement: null,
    };
    const run: BuyerRun = {
      run_id: "run-1",
      stage: "funded",
      settlement,
    };

    const merged = mergeRunState(state, run);

    expect(merged.stage).toBe("funded");
    expect(merged.settlement?.transaction_id).toBe("vf_1");
  });

  it("keeps a cached settlement when the run read omits it", () => {
    const state: BuyerState = { settlement };
    const run: BuyerRun = { run_id: "run-1", stage: "funded" };

    const merged = mergeRunState(state, run);

    expect(merged.settlement).toEqual(settlement);
  });

  it("preserves the state when no run is available", () => {
    const state: BuyerState = { stage: "negotiating" };
    expect(mergeRunState(state, null)).toBe(state);
  });
});
