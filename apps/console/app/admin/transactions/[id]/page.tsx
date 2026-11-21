import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminTransactionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await auth.protect();
  const { id } = await params;
  const detail = await adminJson<Row>(`/v1/admin/transactions/${encodeURIComponent(id)}`);
  return (
    <AdminPage kicker="Platform transaction" title="Transaction detail">
      <pre data-testid="admin-transaction-detail">{JSON.stringify(detail, null, 2)}</pre>
    </AdminPage>
  );
}
