import Link from "next/link";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { EvidenceProgress } from "@/components/seller/evidence-progress";
import { SellerPageHeader } from "@/components/seller/seller-page-header";
import { SellerStat, SellerStatGrid } from "@/components/seller/seller-stat";
import { TransactionStatusBadge } from "@/components/seller/seller-status-badge";
import { Alert } from "@/components/ui/alert";
import { EmptyState } from "@/components/ui/empty-state";
import { loadSeller } from "@/lib/seller-api";
import { transactionProduct } from "@/lib/seller-evidence";
import { money } from "@/lib/format";
import { evidencePercent, needsSellerAttention, nextActionLabel } from "@/lib/seller-status";
import type { SellerTransactionList } from "@/lib/seller-types";

export const dynamic = "force-dynamic";

function countStates(
  counts: Record<string, number>,
  states: string[],
): number {
  return states.reduce((sum, state) => sum + (counts[state] ?? 0), 0);
}

export default async function SellerDashboardPage() {
  const result = await loadSeller<SellerTransactionList>(
    "/seller/transactions?limit=50",
  );

  if (!result.ok) {
    return (
      <>
        <SellerPageHeader
          eyebrow="Seller center"
          title="Dashboard"
          description="Your Verifund fulfillment work at a glance."
        />
        <Alert message={result.error} />
      </>
    );
  }

  const { items, counts_by_state: counts } = result.data;
  const awaiting = countStates(counts, ["FUNDED", "FULFILLMENT_PENDING"]);
  const evidenceRequired = countStates(counts, ["FULFILLMENT_PENDING"]);
  const underVerification = countStates(counts, [
    "VERIFICATION_PENDING",
    "REVIEW_REQUIRED",
  ]);
  const needsAttention = countStates(counts, [
    "REMEDIATION_REQUIRED",
    "DISPUTE_OPEN",
  ]);
  const priority = items
    .filter((item) => needsSellerAttention(item.state))
    .slice(0, 6);

  return (
    <>
      <SellerPageHeader
        eyebrow="Seller center"
        title="Dashboard"
        description="Orders that need your next action, in one place."
        actions={
          <Link href="/seller/fulfillment" className="mm-button mm-button-ink">
            Open fulfillment tasks
            <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        }
      />

      <SellerStatGrid>
        <SellerStat
          label="Awaiting fulfillment"
          value={awaiting}
          detail="Approved, funded orders"
        />
        <SellerStat
          label="Evidence required"
          value={evidenceRequired}
          detail="Need a seller submission"
          tone={evidenceRequired ? "amber" : undefined}
        />
        <SellerStat
          label="Under verification"
          value={underVerification}
          detail="Being reviewed by Verifund"
        />
        <SellerStat
          label="Needs attention"
          value={needsAttention}
          detail="Remediation or dispute"
          tone={needsAttention ? "error" : undefined}
        />
      </SellerStatGrid>

      <section className="mm-panel mm-seller-section" aria-label="Priority tasks">
        <div className="mm-panel-head">
          <div>
            <p className="mm-kicker">Priority</p>
            <h2>Tasks that need you</h2>
          </div>
          <Link href="/seller/fulfillment" className="mm-text-button">
            View all
            <ArrowRight size={12} aria-hidden="true" />
          </Link>
        </div>

        {priority.length === 0 ? (
          <EmptyState
            title="Nothing needs attention"
            body={
              items.length
                ? "All of your orders are either in progress without an open seller action, or closed."
                : "When a transaction is ready for fulfillment, it will appear here."
            }
            action={
              <Link href="/seller/orders" className="mm-button mm-button-outline">
                View orders
              </Link>
            }
          />
        ) : (
          <ul className="mm-seller-task-list">
            {priority.map((item) => (
              <li key={item.transaction_id}>
                <Link
                  href={`/seller/fulfillment/${encodeURIComponent(item.transaction_id)}`}
                  className="mm-seller-task"
                >
                  <div className="mm-seller-task-main">
                    <span className="mm-seller-task-id">
                      {item.transaction_id}
                    </span>
                    <strong>{transactionProduct(item)}</strong>
                    <span className="mm-seller-task-action">
                      {nextActionLabel(item.next_action)} ·{" "}
                      {money(item.amount_cents)}
                    </span>
                  </div>
                  <div className="mm-seller-task-side">
                    <TransactionStatusBadge state={item.state} />
                    <span className="mm-mono-note">
                      {evidencePercent(item.evidence)}% submitted
                    </span>
                  </div>
                  <EvidenceProgress count={item.evidence} showLabel={false} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
