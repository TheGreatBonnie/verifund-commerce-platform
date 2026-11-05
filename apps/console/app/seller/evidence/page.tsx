import Link from "next/link";
import { SellerPageHeader } from "@/components/seller/seller-page-header";
import { SellerStat, SellerStatGrid } from "@/components/seller/seller-stat";
import { TransactionStatusBadge } from "@/components/seller/seller-status-badge";
import { Alert } from "@/components/ui/alert";
import { EmptyState } from "@/components/ui/empty-state";
import { loadSeller } from "@/lib/seller-api";
import { formatDateTime } from "@/lib/format";
import type { SellerEvidenceLibrary } from "@/lib/seller-types";

export const dynamic = "force-dynamic";

export default async function SellerEvidencePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const requirementId =
    typeof query.requirement_id === "string" && query.requirement_id
      ? query.requirement_id
      : undefined;
  const path = requirementId
    ? `/seller/evidence?limit=100&requirement_id=${encodeURIComponent(requirementId)}`
    : "/seller/evidence?limit=100";
  const result = await loadSeller<SellerEvidenceLibrary>(path);

  if (!result.ok) {
    return (
      <>
        <SellerPageHeader
          eyebrow="Trust & verification"
          title="Evidence library"
          description="Evidence you submitted across every transaction."
        />
        <Alert message={result.error} />
      </>
    );
  }

  const items = result.data.items;
  const transactionIds = new Set(items.map((item) => item.transaction_id));
  const clean = items.filter((item) => item.scan_status === "clean").length;
  const requirements = [...new Set(items.map((i) => i.requirement_id).filter(Boolean))] as string[];

  return (
    <>
      <SellerPageHeader
        eyebrow="Trust & verification"
        title="Evidence library"
        description="Evidence submitted across your transactions. Verification outcomes are transaction-level; open the workspace for the per-requirement result."
      />

      <SellerStatGrid>
        <SellerStat label="Submitted items" value={items.length} detail="Across your transactions" />
        <SellerStat
          label="Transactions"
          value={transactionIds.size}
          detail="With submitted evidence"
        />
        <SellerStat
          label="Clean scans"
          value={clean}
          detail="Passed intake scan"
          tone={clean === items.length && items.length > 0 ? "signal" : undefined}
        />
      </SellerStatGrid>

      {requirements.length > 1 ? (
        <nav className="mm-seller-filter-bar" aria-label="Filter by requirement">
          <Link
            href="/seller/evidence"
            aria-current={!requirementId ? "page" : undefined}
            className={!requirementId ? "is-active" : undefined}
          >
            All requirements
          </Link>
          {requirements.map((id) => (
            <Link
              key={id}
              href={`/seller/evidence?requirement_id=${encodeURIComponent(id)}`}
              aria-current={requirementId === id ? "page" : undefined}
              className={requirementId === id ? "is-active" : undefined}
            >
              {id}
            </Link>
          ))}
        </nav>
      ) : null}

      {items.length === 0 ? (
        <EmptyState
          title="No evidence submitted yet"
          body={
            requirementId
              ? `Nothing has been submitted for requirement ${requirementId}.`
              : "Upload evidence from a fulfillment workspace; submissions appear here."
          }
          action={
            <Link href="/seller/fulfillment" className="mm-button mm-button-outline">
              Open fulfillment
            </Link>
          }
        />
      ) : (
        <section className="mm-panel mm-seller-table-panel" aria-label="Evidence submissions">
          <div className="mm-table-scroll">
            <table className="mm-seller-table">
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Requirement</th>
                  <th scope="col">Submitted</th>
                  <th scope="col">Scan</th>
                  <th scope="col">Transaction state</th>
                  <th scope="col">
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={`${item.transaction_id}:${item.evidence_id}`}>
                    <th scope="row">
                      <span className="mm-seller-evidence-name">
                        {item.original_filename}
                      </span>
                      <span className="mm-seller-evidence-id">{item.evidence_id}</span>
                    </th>
                    <td>
                      {item.requirement_id ? (
                        <Link
                          href={`/seller/evidence?requirement_id=${encodeURIComponent(item.requirement_id)}`}
                          className="mm-seller-row-link"
                        >
                          {item.requirement_id}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <time dateTime={item.created_at}>
                        {formatDateTime(item.created_at)}
                      </time>
                      {item.captured_at ? (
                        <span className="mm-seller-cell-note">
                          captured {formatDateTime(item.captured_at)}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <span className="mm-seller-chip">
                        {item.scan_status ?? "received"}
                      </span>
                    </td>
                    <td>
                      <TransactionStatusBadge state={item.transaction_state} />
                    </td>
                    <td>
                      <Link
                        href={`/seller/fulfillment/${encodeURIComponent(item.transaction_id)}`}
                        aria-label={`Open ${item.transaction_id} workspace`}
                        className="mm-seller-row-link"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mm-mono-note mm-seller-table-note">
            {items.length} item{items.length === 1 ? "" : "s"} shown. Per-requirement
            verification lives in each transaction workspace.
          </p>
        </section>
      )}
    </>
  );
}
