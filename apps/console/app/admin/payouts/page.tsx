import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";
import { approvePayout } from "./actions";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminPayoutsPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/transactions?state=funded");
  return (
    <AdminPage kicker="Platform admin" title="Payouts">
      <pre data-testid="admin-payouts">{JSON.stringify(rows, null, 2)}</pre>
      <ul>
        {rows.map((row) => {
          const transactionId = String(row.transaction_id);
          return (
            <li key={transactionId}>
              <span>{transactionId}</span>
              <form
                action={approvePayout.bind(
                  null,
                  transactionId,
                  "Approved from the admin workspace",
                )}
              >
                <button type="submit">Approve payout</button>
              </form>
            </li>
          );
        })}
      </ul>
    </AdminPage>
  );
}
