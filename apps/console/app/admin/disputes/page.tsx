import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminDisputesPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/disputes");

  return (
    <AdminPage
      kicker="Platform admin"
      title="Disputes"
      description="Read-only oversight of platform transaction disputes."
    >
      <div data-testid="admin-disputes">
        <AdminTable
          title="Disputes"
          rows={rows}
          columns={[
            { key: "transaction_id", label: "Transaction" },
            { key: "state", label: "State" },
            { key: "status", label: "Status" },
            { key: "reason_code", label: "Reason" },
            { key: "created_at", label: "Opened" },
          ]}
          detailHref={(row) =>
            `/admin/disputes/${encodeURIComponent(String(row.transaction_id ?? row.id))}`
          }
        />
        <AdminRawDisclosure value={rows} />
      </div>
    </AdminPage>
  );
}
