import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminOverviewPage() {
  await auth.protect();
  const overview = await adminJson<Row>("/v1/admin/overview");
  return (
    <AdminPage kicker="Platform admin" title="Overview">
      <pre data-testid="admin-overview">{JSON.stringify(overview, null, 2)}</pre>
    </AdminPage>
  );
}
