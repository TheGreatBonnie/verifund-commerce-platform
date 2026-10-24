"use client";

import { EmptyState } from "@/components/ui/empty-state";
import { useRuns } from "@/features/runs/use-runs";
import { RunSummaryCard } from "@/features/runs/run-summary-card";

export default function RunsPage() {
  const { runs, isLoading, error } = useRuns();
  if (isLoading) return <EmptyState title="Loading runs" body="Fetching from buyer…" />;
  if (error) return <EmptyState title="Runs unavailable" body={error} />;
  if (runs.length === 0) return <EmptyState title="No runs yet" body="Start a run from the Home page." />;
  return (
    <section className="mm-runs-list">
      <header className="mm-section-head">
        <div>
          <p className="mm-kicker">History</p>
          <h2>Runs</h2>
        </div>
      </header>
      <div className="mm-runs-grid">
        {runs.map((run) => (
          <RunSummaryCard key={run.run_id} run={run} />
        ))}
      </div>
    </section>
  );
}
