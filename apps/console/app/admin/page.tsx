import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import {
  AdminKpis,
  AdminRawDisclosure,
  AdminValue,
} from "@/components/admin/admin-primitives";
import { Panel } from "@/components/ui/panel";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

const QUEUES = [
  { href: "/admin/transactions", label: "Platform transactions" },
  { href: "/admin/payouts", label: "Payout queue" },
  { href: "/admin/disputes", label: "Disputes" },
  { href: "/admin/verification", label: "Seller verification" },
  { href: "/admin/audit", label: "Audit log" },
];

export default async function AdminOverviewPage() {
  await auth.protect();
  const overview = await adminJson<Row>("/v1/admin/overview");
  const currency = String(overview.currency ?? "USD");

  return (
    <AdminPage
      kicker="Platform admin"
      title="Overview"
      description="Platform-held activity across transactions, payouts and disputes."
    >
      <div data-testid="admin-overview">
        <AdminKpis
          items={[
            {
              label: "Pending verifications",
              value: <AdminValue value={overview.pending_verifications ?? null} />,
            },
            {
              label: "Platform-held funds",
              value: (
                <AdminValue
                  field="held_funds_cents"
                  value={overview.held_funds_cents ?? null}
                  currency={currency}
                />
              ),
            },
            {
              label: "Open disputes",
              value: <AdminValue value={overview.open_disputes ?? null} />,
            },
          ]}
        />
        <Panel title="Queues" kicker="Platform admin">
          <ul className="mm-admin-links">
            {QUEUES.map((queue) => (
              <li key={queue.href}>
                <Link href={queue.href}>{queue.label}</Link>
              </li>
            ))}
          </ul>
        </Panel>
        <AdminRawDisclosure value={overview} />
      </div>
    </AdminPage>
  );
}
