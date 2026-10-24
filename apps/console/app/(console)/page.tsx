"use client";

import { useRouter } from "next/navigation";
import { ArrowDownRight } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { useRuns } from "@/features/runs/use-runs";
import { RunSummaryCard } from "@/features/runs/run-summary-card";

const SAMPLE_BRIEF =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

export default function Home() {
  const router = useRouter();
  const { runs } = useRuns();
  const recent = runs.slice(0, 3);

  const runSample = () => {
    const threadId = crypto.randomUUID();
    try {
      window.sessionStorage.setItem("marketmesh:pendingBrief", SAMPLE_BRIEF);
    } catch {
      // ignore
    }
    router.push(`/runs/${threadId}`);
  };

  return (
    <div className="mm-home">
      <Panel>
        <p className="mm-kicker">Sourcing desk</p>
        <h2 className="mm-home-title">
          Offers, not ads.
          <br />
          <em>Decisions, not autopilot.</em>
        </h2>
        <p className="mm-deal-lede">
          A buyer agent discovers independent sellers over Agent Cards, negotiates
          structured offers in private A2A tasks, and brings the award back to a
          human before an order exists.
        </p>
        <div className="mm-home-actions">
          <Button onClick={runSample}>Run sample brief</Button>
        </div>
      </Panel>

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
      ) : (
        <EmptyState
          title="No runs yet"
          body="Run the sample brief to open your first sourcing run."
        />
      )}
    </div>
  );
}
