import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminVerificationPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/verification/pending");
  return (
    <AdminPage kicker="Platform admin" title="Seller verification">
      <pre data-testid="admin-verification">{JSON.stringify(rows, null, 2)}</pre>
    </AdminPage>
  );
}
