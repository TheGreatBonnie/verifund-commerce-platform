import { EventType, type BaseEvent } from "@ag-ui/core";
import { Observable } from "rxjs";

export interface SingleTerminalStreamOptions {
  /**
   * Tool names whose `TOOL_CALL_END` ends the run.
   *
   * CopilotKit's frontend HITL tools are stateless: the agent emits the tool
   * call and its run is expected to finish before the user responds. When the
   * run stays open across the HITL wait, Intelligence keeps the thread locked
   * and the follow-up run dispatched by `respond()` is rejected with a 409
   * `agent_thread_locked`. Ending the stream at the tool-call boundary lets the
   * runtime release the lock before the follow-up starts.
   */
  terminateOnToolCallNames?: ReadonlySet<string>;
}

/**
 * Normalizes an AG-UI event stream so it contains exactly one RUN_STARTED
 * and one terminal event.
 *
 * `@ag-ui/a2a-middleware` starts a fresh orchestration sub-run after each A2A
 * tool call, but reuses the original run id. Every sub-run emits its own
 * RUN_STARTED/RUN_FINISHED pair, so a single logical run reaches downstream
 * consumers (including CopilotKit Intelligence) with duplicate terminal
 * events. Intelligence accepts only one terminal event per run and rejects
 * the second with `terminal_event_already_received`, which aborts the run.
 *
 * This operator forwards the first RUN_STARTED, drops later ones, and holds
 * RUN_FINISHED until it knows whether the run continues: a finish is dropped
 * as soon as another event arrives, and only the final held finish is emitted
 * when the stream completes. RUN_ERROR is forwarded immediately and
 * suppresses any held finish.
 *
 * When `terminateOnToolCallNames` is supplied, the stream is completed as soon
 * as one of those frontend HITL tools finishes its tool call. The synthetic
 * RUN_FINISHED carries the original run's ids so the runtime can settle the
 * run, and completing the observable tears down the upstream subscription so
 * the agent stops streaming.
 */
export function singleTerminalStream(
  source: Observable<BaseEvent>,
  options?: SingleTerminalStreamOptions,
): Observable<BaseEvent> {
  return new Observable<BaseEvent>((subscriber) => {
    let sawRunStarted = false;
    let heldFinish: BaseEvent | null = null;
    let terminal = false;
    let startedEvent: BaseEvent | null = null;
    const toolNamesById = new Map<string, string>();

    const subscription = source.subscribe({
      next(event) {
        if (terminal) {
          return;
        }

        switch (event.type) {
          case EventType.RUN_STARTED:
            if (sawRunStarted) {
              return;
            }
            sawRunStarted = true;
            startedEvent = event;
            subscriber.next(event);
            return;

          case EventType.TOOL_CALL_START: {
            const { toolCallId, toolCallName } = event as BaseEvent & {
              toolCallId?: string;
              toolCallName?: string;
            };
            if (toolCallId && toolCallName) {
              toolNamesById.set(toolCallId, toolCallName);
            }
            // A tool call after a held finish proves the run continues.
            heldFinish = null;
            subscriber.next(event);
            return;
          }

          case EventType.TOOL_CALL_END: {
            // A tool call after a held finish proves the run continues.
            heldFinish = null;
            subscriber.next(event);
            const { toolCallId } = event as BaseEvent & { toolCallId?: string };
            const toolCallName = toolCallId
              ? toolNamesById.get(toolCallId)
              : undefined;
            if (
              toolCallName &&
              options?.terminateOnToolCallNames?.has(toolCallName)
            ) {
              const { threadId, runId } = (startedEvent ?? {}) as {
                threadId?: string;
                runId?: string;
              };
              terminal = true;
              subscriber.next({
                type: EventType.RUN_FINISHED,
                threadId,
                runId,
              } as BaseEvent);
              subscriber.complete();
            }
            return;
          }

          case EventType.RUN_FINISHED:
            // Hold the finish until we know no further sub-run follows.
            heldFinish = event;
            return;

          case EventType.RUN_ERROR:
            heldFinish = null;
            terminal = true;
            subscriber.next(event);
            return;

          default:
            // Any non-terminal event after a finish means the finish belonged
            // to an intermediate sub-run and must not be forwarded.
            heldFinish = null;
            subscriber.next(event);
            return;
        }
      },
      error(error) {
        subscriber.error(error);
      },
      complete() {
        if (heldFinish && !terminal) {
          subscriber.next(heldFinish);
        }
        subscriber.complete();
      },
    });

    return () => subscription.unsubscribe();
  });
}
