import type { AgentRunnerRunRequest, RunnerStartupBoundary } from "@copilotkit/runtime/v2";
import { finalize } from "rxjs";

/**
 * Registers the promise that represents "this run is still executing".
 *
 * On Vercel this must be wired to `after()`/`waitUntil()`: the Intelligence
 * runtime returns its join credentials as soon as the runner channel is joined
 * and then keeps executing the agent in the background of the same invocation.
 * Without a keep-alive the sandbox is frozen when the response is sent, the
 * ingestion socket closes, and Intelligence publishes a RUN_ERROR with
 * `RUNNER_CONNECTION_DROPPED` to the thread channel.
 */
export type KeepAliveHook = (work: Promise<void>) => void;

type StartupBoundaryRunner = {
  runWithStartupBoundary?: (
    request: AgentRunnerRunRequest,
  ) => RunnerStartupBoundary;
};

/**
 * Patch an Intelligence runner so every run registers a keep-alive promise
 * that settles when that run's event stream terminates.
 *
 * Returns `false` (and does nothing) for runners without a startup boundary,
 * which is the SSE/InMemory path: there the run already streams inside the
 * HTTP response, so nothing needs to outlive it.
 *
 * The returned observable must stay single-subscription. Intelligence starts a
 * run from the Observable's subscribe body, so subscribing here as well would
 * start a second run; the promise is settled through `finalize` instead.
 */
export function keepIntelligenceRunsAlive<Runner extends object>(
  runner: Runner,
  keepAlive: KeepAliveHook,
): boolean {
  const target = runner as StartupBoundaryRunner;
  if (typeof target.runWithStartupBoundary !== "function") return false;

  const startRun = target.runWithStartupBoundary.bind(runner);

  target.runWithStartupBoundary = (request) => {
    const run = startRun(request);

    let settle!: () => void;
    const finished = new Promise<void>((resolve) => {
      settle = resolve;
    });

    // `finalize` covers complete, error and an early unsubscribe, so the
    // promise always settles and never leaks into an unhandled rejection.
    const events = run.events.pipe(finalize(() => settle()));

    // When the channel join fails, the handler returns 502 before subscribing.
    run.startup.catch(() => settle());

    keepAlive(finished);

    return { events, startup: run.startup };
  };

  return true;
}
