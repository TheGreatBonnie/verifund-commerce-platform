"use client";

import { useRunLaunch } from "@/features/chat/use-run-launch";

/** Shown when CopilotKit reports that another run holds the thread lock. */
export function ThreadLockNotice({ onDismiss }: { onDismiss: () => void }) {
  const { runOnActiveThread } = useRunLaunch();

  const retry = () => {
    onDismiss();
    runOnActiveThread();
  };

  return (
    <div
      className="mm-chat-approval"
      role="alert"
      data-testid="verifund-thread-lock">
      <p className="mm-kicker">Agent busy</p>
      <p>
        The agent is still working on this conversation. Wait for it to finish,
        then retry.
      </p>
      <button type="button" onClick={retry}>
        Retry
      </button>
    </div>
  );
}
