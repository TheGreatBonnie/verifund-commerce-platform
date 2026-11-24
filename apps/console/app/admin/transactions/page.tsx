import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminTransactionsPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/transactions");

  return (
    <AdminPage
      kicker="Platform admin"
      title="Platform transactions"
      description="Transactions held by the configured PayPal platform account."
    >
      <div data-testid="admin-transactions">
        <AdminTable
          title="Platform transactions"
          rows={rows}
          currency={String(rows?.[0]?.currency ?? "USD")}
          columns={[
            { key: "transaction_id", label: "Transaction" },
            { key: "state", label: "State" },
            { key: "seller_name", label: "Seller" },
            { key: "buyer_name", label: "Buyer" },
            { key: "amount_cents", label: "Amount" },
            { key: "created_at", label: "Created" },
          ]}
          detailHref={(row) =>
            `/admin/transactions/${encodeURIComponent(String(row.transaction_id))}`
          }
        />
        <AdminRawDisclosure value={rows} />
      </div>
    </AdminPage>
  );
}
