import { describe, expect, it } from "vitest";
import { from, lastValueFrom, Observable, toArray } from "rxjs";
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

const toolCallStart = (
  toolCallId: string,
  toolCallName: string,
): BaseEvent =>
  ({
    type: EventType.TOOL_CALL_START,
    toolCallId,
    toolCallName,
  }) as BaseEvent;

const toolCallArgs = (toolCallId: string): BaseEvent =>
  ({
    type: EventType.TOOL_CALL_ARGS,
    toolCallId,
    delta: "{}",
  }) as BaseEvent;

const toolCallEnd = (toolCallId: string): BaseEvent =>
  ({ type: EventType.TOOL_CALL_END, toolCallId }) as BaseEvent;

const toolCallResult = (toolCallId: string): BaseEvent =>
  ({
    type: EventType.TOOL_CALL_RESULT,
    toolCallId,
    messageId: "tool-message-1",
    content: "ok",
  }) as BaseEvent;

const HITL_TOOL_NAMES = new Set(["request_verifund_agreement_approval"]);

async function collect(events: BaseEvent[]): Promise<BaseEvent[]> {
  return lastValueFrom(from(events).pipe(singleTerminalStream, toArray()));
}

async function collectWithHitlNames(
  events: BaseEvent[],
): Promise<BaseEvent[]> {
  return lastValueFrom(
    from(events).pipe(
      (source) =>
        singleTerminalStream(source, {
          terminateOnToolCallNames: HITL_TOOL_NAMES,
        }),
      toArray(),
    ),
  );
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

  it("terminates the run as soon as a frontend HITL tool call ends", async () => {
    // The orchestrator keeps streaming after emitting the HITL tool call (a
    // text turn and its own RUN_FINISHED). The run must still terminate at the
    // tool-call boundary so the Intelligence thread lock is released before
    // the HITL response dispatches the follow-up run.
    const events = [
      runStarted(),
      toolCallStart("call-1", "request_verifund_agreement_approval"),
      toolCallArgs("call-1"),
      toolCallEnd("call-1"),
      textStart(),
      textContent(),
      textEnd(),
      runFinished(),
    ];

    const result = await collectWithHitlNames(events);

    expect(result.map((event) => event.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.TOOL_CALL_START,
      EventType.TOOL_CALL_ARGS,
      EventType.TOOL_CALL_END,
      EventType.RUN_FINISHED,
    ]);
    expect(result.at(-1)).toMatchObject({
      threadId: "thread-1",
      runId: "run-1",
    });
  });

  it("does not terminate for a non-HITL backend tool call", async () => {
    const events = [
      runStarted(),
      toolCallStart("call-1", "search_marketplace_products"),
      toolCallArgs("call-1"),
      toolCallEnd("call-1"),
      toolCallResult("call-1"),
      runFinished(),
    ];

    expect(await collectWithHitlNames(events)).toEqual(events);
  });

  it("drops a held finish when a tool call proves the run continues", async () => {
    // A stale sub-run finish before a backend tool call must not be emitted;
    // TOOL_CALL_START/END are ordinary continuation events for non-HITL tools.
    const events = [
      runStarted(),
      runFinished(),
      toolCallStart("call-1", "search_marketplace_products"),
      toolCallEnd("call-1"),
      toolCallResult("call-1"),
    ];

    const result = await collectWithHitlNames(events);

    expect(result.map((event) => event.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.TOOL_CALL_START,
      EventType.TOOL_CALL_END,
      EventType.TOOL_CALL_RESULT,
    ]);
  });

  it("unsubscribes from the source when a HITL tool call terminates the run", async () => {
    let tornDown = false;
    const source = new Observable<BaseEvent>((subscriber) => {
      subscriber.next(runStarted());
      subscriber.next(
        toolCallStart("call-1", "request_verifund_agreement_approval"),
      );
      subscriber.next(toolCallEnd("call-1"));
      // The source never completes on its own while the HITL is outstanding.
      return () => {
        tornDown = true;
      };
    });

    const result = await lastValueFrom(
      singleTerminalStream(source, {
        terminateOnToolCallNames: HITL_TOOL_NAMES,
      }).pipe(toArray()),
    );

    expect(tornDown).toBe(true);
    expect(result.map((event) => event.type)).toEqual([
      EventType.RUN_STARTED,
      EventType.TOOL_CALL_START,
      EventType.TOOL_CALL_END,
      EventType.RUN_FINISHED,
    ]);
  });
});
