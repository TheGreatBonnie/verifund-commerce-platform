import type { BuyerRun } from "./api";
import type { BuyerState } from "./types";

export function mergeRunState(
  state: BuyerState,
  run: BuyerRun | null,
): BuyerState {
  if (!run) return state;
  return {
    ...state,
    run_id: run.run_id ?? state.run_id,
    task_id: run.run_id ?? state.task_id,
    stage: run.stage ?? state.stage,
    mandate: run.mandate ?? state.mandate,
    award: run.award ?? state.award,
    order: run.order ?? state.order,
    error: run.error ?? state.error,
    settlement: run.settlement ?? state.settlement ?? null,
  };
}
