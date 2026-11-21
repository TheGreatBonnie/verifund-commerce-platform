import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminDisputesPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/disputes");
  return (
    <AdminPage kicker="Platform admin" title="Disputes">
      <pre data-testid="admin-disputes">{JSON.stringify(rows, null, 2)}</pre>
    </AdminPage>
  );
}
