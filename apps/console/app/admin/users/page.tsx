import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminUsersPage() {
  await auth.protect();
  const body = await adminJson<Row>("/api/admin/users");
  return (
    <AdminPage kicker="Platform admin" title="Users">
      <pre data-testid="admin-users">{JSON.stringify(body, null, 2)}</pre>
    </AdminPage>
  );
}
