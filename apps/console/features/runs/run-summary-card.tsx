import Link from "next/link";
import { money } from "@/lib/format";
import type { BuyerRun } from "@/lib/api";
import { RunStatusBadge } from "./run-status-badge";

export function RunSummaryCard({ run }: { run: BuyerRun }) {
  const mandate = run.mandate;
  const title = mandate
    ? `${mandate.quantity ?? ""} × ${mandate.product_hint ?? "run"}`
    : run.run_id;
  return (
    <Link href={`/runs/${run.run_id}`} className="mm-run-card">
      <div className="mm-run-card-head">
        <h3>{title}</h3>
        <RunStatusBadge stage={run.stage} />
      </div>
      <div className="mm-run-card-meta">
        {mandate?.max_total_cents ? <span>Ceiling {money(mandate.max_total_cents)}</span> : null}
        {run.award?.winner ? <span>Winner {run.award.winner.seller_name}</span> : null}
        {run.order?.order_id ? <span>Order {run.order.order_id}</span> : null}
        <span>{run.updated_at ? new Date(run.updated_at).toLocaleString() : "—"}</span>
      </div>
    </Link>
  );
}
