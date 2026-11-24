import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { AdminFields } from "@/components/admin/admin-primitives";
import { Panel } from "@/components/ui/panel";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, any>;

const SECRET_KEY = /(secret|token|password|api_key|client_secret|webhook)/i;

function redact(settings: Row): Row {
  return Object.fromEntries(
    Object.entries(settings).map(([key, value]) => [
      key,
      SECRET_KEY.test(key) && value ? "••••••••" : value,
    ]),
  );
}

export default async function AdminSettingsPage() {
  await auth.protect();
  const settings = await adminJson<Row>("/v1/admin/settings");
  const visible = redact(settings);

  return (
    <AdminPage
      kicker="Platform admin"
      title="Settings"
      description="Configured platform PayPal account and linkage."
    >
      <div data-testid="admin-settings">
        <Panel title="Platform settings" kicker="Backend configuration">
          <AdminFields
            data={visible}
            columns={[
              "paypal_platform_email",
              "paypal_environment",
              "platform_account_email",
              "updated_at",
            ]}
          />
        </Panel>
        <p className="mm-admin-note">
          Sensitive values are redacted and are not available in the page source.
        </p>
      </div>
    </AdminPage>
  );
}
