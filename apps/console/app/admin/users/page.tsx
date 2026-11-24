import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminUsersPage() {
  await auth.protect();
  const body = await adminJson<Row | Row[]>("/api/admin/users");
  const users = Array.isArray(body)
    ? body
    : Array.isArray(body.users)
      ? body.users
      : [];

  return (
    <AdminPage
      kicker="Platform admin"
      title="Users"
      description="Read-only directory of users and platform roles."
    >
      <div data-testid="admin-users">
        <AdminTable
          title="Users"
          rows={users}
          columns={[
            { key: "id", label: "User" },
            { key: "email", label: "Email" },
            { key: "roles", label: "Roles" },
            { key: "is_platform_admin", label: "Platform admin" },
          ]}
        />
        <AdminRawDisclosure value={body} />
      </div>
    </AdminPage>
  );
}
