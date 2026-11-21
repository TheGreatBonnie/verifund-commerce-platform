import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminAuditPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/audit");
  return (
    <AdminPage kicker="Platform admin" title="Audit log">
      <pre data-testid="admin-audit">{JSON.stringify(rows, null, 2)}</pre>
    </AdminPage>
  );
}
