import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminTransactionAuditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await auth.protect();
  const { id } = await params;
  const rows = await adminJson<Row[]>(
    `/v1/admin/transactions/${encodeURIComponent(id)}/audit`,
  );
  return (
    <AdminPage kicker="Platform transaction" title="Transaction audit">
      <pre data-testid="admin-transaction-audit">{JSON.stringify(rows, null, 2)}</pre>
    </AdminPage>
  );
}
