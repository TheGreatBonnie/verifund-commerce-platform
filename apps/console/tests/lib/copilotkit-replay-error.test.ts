import { describe, expect, it } from "vitest";
import * as CopilotKitV2 from "@copilotkit/react-core/v2";

type ReplayErrorCtor = new (
  threadId: string,
  runId: string | null,
) => Error & { code: string; threadId: string; runId: string | null };

/**
 * Locks in the public error contract introduced by CopilotKit 1.89.0. The
 * console does not consume this error yet; when it does, the typed code lets
 * it tell a failed history replay apart from a live run error.
 */
describe("CopilotKit replay error classification", () => {
  it("exposes a typed replay-failure error with a stable code", () => {
    const ReplayError = (CopilotKitV2 as Record<string, unknown>)
      .IntelligenceReplayFailedError as ReplayErrorCtor | undefined;

    expect(typeof ReplayError).toBe("function");

    const error = new ReplayError!("replay-thread", null);
    expect(error).toBeInstanceOf(Error);
    expect(error.code).toBe("INTELLIGENCE_REPLAY_FAILED");
    expect(error.threadId).toBe("replay-thread");
    expect(error.runId).toBeNull();
  });
});
