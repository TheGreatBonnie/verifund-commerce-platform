import { EventType, type BaseEvent } from "@ag-ui/core";
import { Observable } from "rxjs";

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
 */
export function singleTerminalStream(
  source: Observable<BaseEvent>,
): Observable<BaseEvent> {
  return new Observable<BaseEvent>((subscriber) => {
    let sawRunStarted = false;
    let heldFinish: BaseEvent | null = null;
    let terminal = false;

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
            subscriber.next(event);
            return;

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
