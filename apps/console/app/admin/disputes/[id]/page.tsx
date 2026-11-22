import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminFields,
  AdminRawDisclosure,
  AdminTable,
} from "@/components/admin/admin-primitives";
import { Panel } from "@/components/ui/panel";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

export default async function AdminDisputeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await auth.protect();
  const { id } = await params;
  const detail = await adminJson<Row>(
    `/v1/admin/disputes/${encodeURIComponent(id)}`,
  );
  const nestedKeys = ["evidence", "timeline", "events", "audit", "messages"];

  return (
    <AdminPage
      kicker="Platform admin"
      title="Dispute detail"
      description="Evidence and timeline for this dispute; no refund is executed here."
    >
      <div data-testid="admin-dispute-detail">
        <Panel title="Dispute" kicker="Platform admin">
          <AdminFields data={detail} exclude={nestedKeys} />
        </Panel>
        {Array.isArray(detail.evidence) ? (
          <Panel title="Evidence" kicker="Verification">
            <AdminTable title="Evidence" rows={detail.evidence} />
          </Panel>
        ) : null}
        {Array.isArray(detail.timeline ?? detail.events) ? (
          <Panel title="Timeline" kicker="Dispute events">
            <AdminTable
              title="Dispute events"
              rows={detail.timeline ?? detail.events}
            />
          </Panel>
        ) : null}
        <AdminRawDisclosure value={detail} />
      </div>
    </AdminPage>
  );
}
