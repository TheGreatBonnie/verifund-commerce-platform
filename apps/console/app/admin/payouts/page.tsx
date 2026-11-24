import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";
import { approvePayout } from "./actions";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminPayoutsPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/transactions?state=funded");

  return (
    <AdminPage
      kicker="Platform admin"
      title="Payouts"
      description="Funded transactions awaiting payout release."
    >
      <div data-testid="admin-payouts">
        <AdminTable
          title="Payout queue"
          rows={rows}
          currency={String(rows?.[0]?.currency ?? "USD")}
          columns={[
            { key: "transaction_id", label: "Transaction" },
            { key: "seller_name", label: "Seller" },
            { key: "amount_cents", label: "Amount" },
            { key: "state", label: "State" },
            {
              key: "action",
              label: "Action",
              render: (_value, row) => {
                const transactionId = String(row.transaction_id);
                return (
                  <form
                    action={approvePayout.bind(
                      null,
                      transactionId,
                      "Approved from the admin workspace",
                    )}
                  >
                    <button type="submit" className="mm-button">
                      Approve payout
                    </button>
                  </form>
                );
              },
            },
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
