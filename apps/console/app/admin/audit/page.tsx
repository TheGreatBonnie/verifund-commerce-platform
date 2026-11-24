import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminAuditPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/audit");

  return (
    <AdminPage
      kicker="Platform admin"
      title="Audit log"
      description="Platform-wide actions, oldest first."
    >
      <div data-testid="admin-audit">
        <AdminTable
          title="Audit log"
          rows={rows}
          columns={[
            { key: "at", label: "When" },
            { key: "actor", label: "Actor" },
            { key: "action", label: "Action" },
            { key: "target", label: "Target" },
            { key: "outcome", label: "Outcome" },
          ]}
        />
        <AdminRawDisclosure value={rows} />
      </div>
    </AdminPage>
  );
}
