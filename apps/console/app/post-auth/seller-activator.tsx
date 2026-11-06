"use client";

import { CreateOrganization, useOrganizationList, useUser } from "@clerk/nextjs";
import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";

export function SellerActivator() {
  const { user } = useUser();
  const { isLoaded, userMemberships, createOrganization, setActive } =
    useOrganizationList({ userMemberships: true });

  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const hasRun = useRef(false);

  const membershipsLoaded = isLoaded && !userMemberships?.isLoading;
  const existingOrgs = userMemberships?.data ?? [];

  useEffect(() => {
    if (!membershipsLoaded || hasRun.current || existingOrgs.length === 0) return;
    hasRun.current = true;
    const orgId = existingOrgs[0].organization.id;
    setActive!({ organization: orgId })
      .then(() => window.location.assign("/seller/onboarding"))
      .catch((err) => {
        console.error("seller activation: setActive failed", err);
        setError("Could not activate your organization. Please try again.");
        hasRun.current = false;
      });
  }, [membershipsLoaded, existingOrgs, setActive]);

  const handleCreate = async () => {
    if (hasRun.current || creating) return;
    hasRun.current = true;
    setCreating(true);
    setError(null);
    try {
      const org = await createOrganization!({
        name: user?.firstName ? `${user.firstName}'s business` : "My business",
      });
      await setActive!({ organization: org.id });
      window.location.assign("/seller/onboarding");
    } catch (err) {
      console.error("seller activation: create/setActive failed", err);
      hasRun.current = false;
      const msg =
        err instanceof Error && /limit/i.test(err.message)
          ? "You've reached the organization limit on this Clerk instance. Remove unused organizations in the Clerk dashboard, or continue with an existing one below."
          : "Could not create your organization. Please try again.";
      setError(msg);
    } finally {
      setCreating(false);
    }
  };

  const shell: React.CSSProperties = {
    minHeight: "100dvh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "clamp(24px, 4vw, 48px)",
  };

  if (!isLoaded || userMemberships?.isLoading) {
    return (
      <main className="mm-auth-page" style={shell}>
        <Panel kicker="Seller onboarding" title="Setting up your account">
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--muted)" }}>
            <Loader2 size={18} className="is-spinning" aria-hidden="true" />
            <span>Loading your organizations…</span>
          </div>
        </Panel>
      </main>
    );
  }

  if (error) {
    return (
      <main className="mm-auth-page" style={shell}>
        <Panel kicker="Seller onboarding" title="Something went wrong">
          <p role="alert" style={{ color: "var(--signal-deep)", margin: 0 }}>
            {error}
          </p>
          {existingOrgs.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{ margin: "0 0 8px", fontWeight: 500 }}>Continue with an existing organization:</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {existingOrgs.map((m) => (
                  <Button
                    key={m.id}
                    variant="outline"
                    onClick={async () => {
                      try {
                        await setActive!({ organization: m.organization.id });
                        window.location.assign("/seller/onboarding");
                      } catch (err) {
                        console.error("seller activation: setActive failed", err);
                        setError("Could not activate that organization.");
                      }
                    }}
                  >
                    {m.organization.name}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {existingOrgs.length === 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{ margin: "0 0 8px", fontWeight: 500 }}>Or create one with Clerk:</p>
              <CreateOrganization />
            </div>
          )}
          <div style={{ marginTop: 16 }}>
            <Button variant="ghost" onClick={() => { hasRun.current = false; setError(null); }}>
              Retry
            </Button>
          </div>
        </Panel>
      </main>
    );
  }

  if (existingOrgs.length > 0) {
    return (
      <main className="mm-auth-page" style={shell}>
        <Panel kicker="Seller onboarding" title="Activating your organization">
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--muted)" }}>
            <Loader2 size={18} className="is-spinning" aria-hidden="true" />
            <span>Activating {existingOrgs[0].organization.name}…</span>
          </div>
        </Panel>
      </main>
    );
  }

  return (
    <main className="mm-auth-page" style={shell}>
      <Panel kicker="Seller onboarding" title="Create your seller organization">
        <p style={{ margin: "0 0 16px", color: "var(--muted)" }}>
          You don&apos;t have a seller organization yet. Create one to start onboarding.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Button onClick={handleCreate} disabled={creating} loading={creating}>
            {creating ? "Creating…" : "Create my seller organization"}
          </Button>
          <div>
            <p style={{ margin: "0 0 8px", fontWeight: 500, fontSize: 14 }}>Or use Clerk&apos;s organization creator:</p>
            <CreateOrganization />
          </div>
        </div>
      </Panel>
    </main>
  );
}
