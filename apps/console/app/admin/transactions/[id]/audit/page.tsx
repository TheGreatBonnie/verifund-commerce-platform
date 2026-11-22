import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

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
    <AdminPage
      kicker="Platform transaction"
      title="Transaction audit"
      description="Who changed this transaction, when, and with what outcome."
    >
      <div data-testid="admin-transaction-audit">
        <AdminTable
          title="Transaction audit"
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
