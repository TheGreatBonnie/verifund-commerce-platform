import { describe, expect, it, vi } from "vitest";
import { Observable, Subject } from "rxjs";
import { keepIntelligenceRunsAlive } from "@/lib/copilot-run-keepalive";

type RunRequest = { threadId: string };

/** A runner shaped like IntelligenceAgentRunner, with a controllable stream. */
function makeRunner() {
  const subject = new Subject<{ type: string }>();
  const requests: RunRequest[] = [];
  let subscriptions = 0;
  let startupResolve!: () => void;
  let startupReject!: (error: Error) => void;
  const startup = new Promise<void>((resolve, reject) => {
    startupResolve = resolve;
    startupReject = reject;
  });

  const runner = {
    runWithStartupBoundary(request: RunRequest) {
      requests.push(request);
      const events = new Observable<{ type: string }>((subscriber) => {
        subscriptions += 1;
        return subject.subscribe(subscriber);
      });
      return { events, startup };
    },
  };

  return {
    runner,
    subject,
    requests,
    startupResolve: () => startupResolve(),
    startupReject: (error: Error) => startupReject(error),
    subscriptionCount: () => subscriptions,
  };
}

function install(runner: object) {
  const work: Promise<void>[] = [];
  const installed = keepIntelligenceRunsAlive(runner, (pending) => {
    work.push(pending);
  });
  return { installed, work };
}

async function isSettled(promise: Promise<void>) {
  let settled = false;
  promise.then(
    () => {
      settled = true;
    },
    () => {
      settled = false;
    },
  );
  await Promise.resolve();
  await Promise.resolve();
  return settled;
}

describe("keepIntelligenceRunsAlive", () => {
  it("registers one keep-alive promise per run", () => {
    const { runner } = makeRunner();
    const { installed, work } = install(runner);

    expect(installed).toBe(true);

    runner.runWithStartupBoundary({ threadId: "thread_1" });
    runner.runWithStartupBoundary({ threadId: "thread_2" });

    expect(work).toHaveLength(2);
  });

  it("keeps the promise pending while the run is streaming", async () => {
    const { runner, subject } = makeRunner();
    const { work } = install(runner);

    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });
    const subscription = run.events.subscribe(() => {});
    subject.next({ type: "RUN_STARTED" });

    expect(await isSettled(work[0])).toBe(false);

    subscription.unsubscribe();
    subject.complete();
  });

  it("settles the keep-alive promise when the run completes", async () => {
    const { runner, subject } = makeRunner();
    const { work } = install(runner);

    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });
    run.events.subscribe({ error: () => {} });

    subject.complete();

    await expect(work[0]).resolves.toBeUndefined();
  });

  it("settles instead of rejecting when the run errors", async () => {
    const { runner, subject } = makeRunner();
    const { work } = install(runner);

    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });
    run.events.subscribe({ error: () => {} });

    subject.error(new Error("runner failed"));

    await expect(work[0]).resolves.toBeUndefined();
  });

  it("settles when the caller unsubscribes early", async () => {
    const { runner } = makeRunner();
    const { work } = install(runner);

    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });
    const subscription = run.events.subscribe(() => {});
    subscription.unsubscribe();

    await expect(work[0]).resolves.toBeUndefined();
  });

  it("settles when startup rejects and the stream is never subscribed", async () => {
    const { runner, startupReject } = makeRunner();
    const { work } = install(runner);

    runner.runWithStartupBoundary({ threadId: "thread_1" });
    const rejection = new Error("join failed");
    startupReject(rejection);
    // The rejection still reaches the route handler, which returns a 502.
    await expect(runner.runWithStartupBoundary({ threadId: "thread_2" }).startup).rejects.toThrow(
      "join failed",
    );

    await expect(work[0]).resolves.toBeUndefined();
    void rejection;
  });

  it("does not subscribe to the run itself", () => {
    const { runner, subscriptionCount } = makeRunner();
    install(runner);

    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });

    // A second subscription would start a second Intelligence run.
    expect(subscriptionCount()).toBe(0);

    const subscription = run.events.subscribe(() => {});
    expect(subscriptionCount()).toBe(1);
    subscription.unsubscribe();
  });

  it("passes the original events through unchanged", () => {
    const { runner, subject } = makeRunner();
    install(runner);

    const seen: { type: string }[] = [];
    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });
    const subscription = run.events.subscribe((event) => seen.push(event));

    const event = { type: "RUN_STARTED" };
    subject.next(event);

    expect(seen).toEqual([event]);
    subscription.unsubscribe();
  });

  it("returns the original startup promise to the handler", () => {
    const { runner, startupResolve } = makeRunner();
    const { work } = install(runner);

    const run = runner.runWithStartupBoundary({ threadId: "thread_1" });

    startupResolve();
    expect(run.startup).toBeInstanceOf(Promise);

    return run.startup.then(async () => {
      // Startup did not settle the run; only the stream does.
      expect(await isSettled(work[0])).toBe(false);
    });
  });

  it("keeps the runner as the receiver of the original method", () => {
    const calls: unknown[] = [];
    const runner = {
      label: "intelligence",
      runWithStartupBoundary(this: { label: string }) {
        calls.push(this.label);
        return { events: new Observable(() => {}), startup: Promise.resolve() };
      },
    };

    install(runner);
    runner.runWithStartupBoundary();

    expect(calls).toEqual(["intelligence"]);
  });

  it("leaves runners without a startup boundary untouched", () => {
    const runner = { run: vi.fn() };

    const { installed, work } = install(runner);

    expect(installed).toBe(false);
    expect(work).toHaveLength(0);
    expect(runner).toEqual({ run: expect.any(Function) });
  });
});
