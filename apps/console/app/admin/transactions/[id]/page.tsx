import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminFields,
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { Panel } from "@/components/ui/panel";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminTransactionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await auth.protect();
  const { id } = await params;
  const detail = await adminJson<Row>(`/v1/admin/transactions/${encodeURIComponent(id)}`);
  const nestedKeys = [
    "agreement",
    "payment",
    "timeline",
    "evidence",
    "audit",
    "ledger",
    "platform_cash",
    "held_funds",
  ];

  return (
    <AdminPage
      kicker="Platform transaction"
      title="Transaction detail"
      description="Agreement, participants, funds and settlement history."
    >
      <div data-testid="admin-transaction-detail">
        <Panel title="Transaction" kicker="Platform transaction">
          <AdminFields
            data={detail}
            columns={[
              "transaction_id",
              "state",
              "status",
              "currency",
              "amount_cents",
              "seller_name",
              "buyer_name",
              "platform_account_email",
              "created_at",
              "updated_at",
            ]}
            exclude={nestedKeys}
            currency={String(detail.currency ?? "USD")}
          />
        </Panel>

        {detail.agreement ? (
          <Panel title="Agreement" kicker="Recorded terms">
            <AdminFields
              data={detail.agreement}
              currency={String(detail.currency ?? "USD")}
            />
          </Panel>
        ) : null}

        {detail.payment ? (
          <Panel title="Payment" kicker="Funding record">
            <AdminFields
              data={detail.payment}
              currency={String(detail.currency ?? "USD")}
            />
          </Panel>
        ) : null}

        {detail.platform_cash || detail.held_funds ? (
          <Panel title="Funds" kicker="Platform ledger">
            <AdminFields
              data={{
                platform_cash: detail.platform_cash ?? null,
                held_funds: detail.held_funds ?? null,
              }}
              currency={String(detail.currency ?? "USD")}
            />
          </Panel>
        ) : null}

        {Array.isArray(detail.evidence) ? (
          <Panel title="Evidence" kicker="Verification">
            <AdminTable title="Evidence" rows={detail.evidence} />
          </Panel>
        ) : null}

        {Array.isArray(detail.timeline) ? (
          <Panel title="Timeline" kicker="Settlement events">
            <AdminTable title="Settlement events" rows={detail.timeline} />
          </Panel>
        ) : null}

        <p className="mm-admin-links">
          <Link href={`/admin/transactions/${encodeURIComponent(id)}/audit`}>
            View transaction audit
          </Link>
        </p>
        <AdminRawDisclosure value={detail} />
      </div>
    </AdminPage>
  );
}
