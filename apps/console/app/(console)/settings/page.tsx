"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { config } from "@/lib/config";

export default function SettingsPage() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const reset = () => {
    qc.clear();
    try {
      window.localStorage.clear();
      window.sessionStorage.clear();
    } catch {
      // ignore
    }
    window.location.reload();
  };

  return (
    <Panel title="Settings" kicker="Console">
      <dl className="mm-settings-list">
        <div>
          <dt>LLM mode</dt>
          <dd>{config.llmMode}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{config.modelLabel}</dd>
        </div>
        <div>
          <dt>Threads enabled</dt>
          <dd>{config.threadsEnabled ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Buyer API</dt>
          <dd>{config.buyerApiUrl}</dd>
        </div>
        <div>
          <dt>Registry</dt>
          <dd>{config.registryUrl}</dd>
        </div>
      </dl>

      <div className="mm-settings-danger">
        {!confirming ? (
          <Button variant="danger" onClick={() => setConfirming(true)}>
            Reset local state
          </Button>
        ) : (
          <>
            <p>This clears cached runs and reloads the console. Continue?</p>
            <Button variant="danger" onClick={reset}>
              Confirm reset
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </>
        )}
      </div>
    </Panel>
  );
}
