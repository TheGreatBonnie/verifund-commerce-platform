import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminTransactionsPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/transactions");
  return (
    <AdminPage kicker="Platform admin" title="Platform transactions">
      <pre data-testid="admin-transactions">{JSON.stringify(rows, null, 2)}</pre>
    </AdminPage>
  );
}
