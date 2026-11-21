import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminSettingsPage() {
  await auth.protect();
  const settings = await adminJson<Row>("/v1/admin/settings");
  return (
    <AdminPage kicker="Platform admin" title="Settings">
      <pre data-testid="admin-settings">{JSON.stringify(settings, null, 2)}</pre>
    </AdminPage>
  );
}
