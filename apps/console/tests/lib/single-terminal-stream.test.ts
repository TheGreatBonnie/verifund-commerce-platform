import { describe, expect, it } from "vitest";
import { from, lastValueFrom, toArray } from "rxjs";
import { EventType, type BaseEvent } from "@ag-ui/core";
import { singleTerminalStream } from "@/lib/single-terminal-stream";

const runStarted = (runId = "run-1"): BaseEvent =>
  ({ type: EventType.RUN_STARTED, threadId: "thread-1", runId }) as BaseEvent;

const runFinished = (runId = "run-1"): BaseEvent =>
  ({ type: EventType.RUN_FINISHED, threadId: "thread-1", runId }) as BaseEvent;

const runError = (message = "boom"): BaseEvent =>
  ({ type: EventType.RUN_ERROR, message }) as BaseEvent;

const textStart = (messageId = "message-1"): BaseEvent =>
  ({ type: EventType.TEXT_MESSAGE_START, messageId, role: "assistant" }) as BaseEvent;

const textContent = (messageId = "message-1"): BaseEvent =>
  ({
    type: EventType.TEXT_MESSAGE_CONTENT,
    messageId,
    delta: "hello",
  }) as BaseEvent;

const textEnd = (messageId = "message-1"): BaseEvent =>
  ({ type: EventType.TEXT_MESSAGE_END, messageId }) as BaseEvent;

async function collect(events: BaseEvent[]): Promise<BaseEvent[]> {
  return lastValueFrom(from(events).pipe(singleTerminalStream, toArray()));
}

describe("singleTerminalStream", () => {
  it("collapses a middleware stream with a second sub-run into one start and one finish", async () => {
    const events = [
      runStarted(),
      textStart(),
      textContent(),
      textEnd(),
      runFinished(),
      runStarted(),
      textStart("message-2"),
      textContent("message-2"),
      textEnd("message-2"),
      runFinished(),
    ];

    const result = await collect(events);

    expect(result.filter((event) => event.type === EventType.RUN_STARTED)).toHaveLength(1);
    expect(result.filter((event) => event.type === EventType.RUN_FINISHED)).toHaveLength(1);
    expect(result.at(-1)?.type).toBe(EventType.RUN_FINISHED);

    // The stale finish from the first sub-run must not leak through.
    const finishIndex = result.findIndex(
      (event) => event.type === EventType.RUN_FINISHED,
    );
    expect(result.slice(0, finishIndex).map((event) => event.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.TEXT_MESSAGE_END,
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.TEXT_MESSAGE_END,
    ]);
  });

  it("passes a single-run stream through unchanged", async () => {
    const events = [
      runStarted(),
      textStart(),
      textContent(),
      textEnd(),
      runFinished(),
    ];

    expect(await collect(events)).toEqual(events);
  });

  it("drops a finish as soon as another event proves the run continues", async () => {
    const events = [
      runStarted(),
      runFinished(),
      textStart(),
      runFinished(),
    ];

    const result = await collect(events);

    expect(result.map((event) => event.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.TEXT_MESSAGE_START,
      EventType.RUN_FINISHED,
    ]);
  });

  it("keeps only the latest finish when finishes arrive back to back", async () => {
    const first = runFinished("run-1");
    const second = runFinished("run-2");

    const result = await collect([runStarted(), first, second]);

    expect(result).toEqual([runStarted(), second]);
  });

  it("forwards a run error and never emits a held finish afterwards", async () => {
    const events = [runStarted(), runFinished(), runError()];

    const result = await collect(events);

    expect(result.map((event) => event.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.RUN_ERROR,
    ]);
  });
});
