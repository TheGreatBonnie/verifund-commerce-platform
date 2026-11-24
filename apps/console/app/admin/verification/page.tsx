import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminVerificationPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/verification/pending");

  return (
    <AdminPage
      kicker="Platform admin"
      title="Seller verification"
      description="Sellers awaiting a verification decision."
    >
      <div data-testid="admin-verification">
        <AdminTable
          title="Pending verifications"
          rows={rows}
          columns={[
            { key: "seller_id", label: "Seller" },
            { key: "seller_name", label: "Name" },
            { key: "status", label: "Status" },
            { key: "submitted_at", label: "Submitted" },
            { key: "reason", label: "Reason" },
          ]}
        />
        <AdminRawDisclosure value={rows} />
      </div>
    </AdminPage>
  );
}
