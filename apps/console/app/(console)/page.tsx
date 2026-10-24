"use client";

import { EmptyState } from "@/components/ui/empty-state";
import { ConsoleShell } from "@/features/deal-room/console-shell";
import { useRuns } from "@/features/runs/use-runs";
import { RunSummaryCard } from "@/features/runs/run-summary-card";

export default function Home() {
  const { runs } = useRuns();
  const recent = runs.slice(0, 3);
  return (
    <>
      <ConsoleShell />
      {recent.length > 0 ? (
        <section className="mm-recent-runs">
          <header className="mm-section-head">
            <div>
              <p className="mm-kicker">History</p>
              <h2>Recent runs</h2>
            </div>
          </header>
          <div className="mm-runs-grid">
            {recent.map((run) => (
              <RunSummaryCard key={run.run_id} run={run} />
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}
