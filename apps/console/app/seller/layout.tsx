import { redirect } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, LogOut, ShieldCheck } from "lucide-react";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { SellerNav } from "@/components/seller/seller-nav";
import { consoleSession } from "@/lib/console-session";
import { sellerAccess } from "@/lib/seller-access";
import { signOutAction } from "./actions";

export const dynamic = "force-dynamic";

export default async function SellerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { orgId } = await consoleSession();
  const access = await sellerAccess(orgId);
  if (access === "none") redirect("/");
  if (access === "onboarding") redirect("/seller/onboarding");

  return (
    <div className="mm-seller-shell" suppressHydrationWarning>
      <aside className="mm-seller-sidebar">
        <Link href="/seller/dashboard" className="mm-seller-brand">
          <span className="mm-seller-brand-mark" aria-hidden="true">
            <ShieldCheck size={19} />
          </span>
          <span>
            <strong>verifund</strong>
            <small>Seller center</small>
          </span>
        </Link>

        <p className="mm-seller-nav-label">Workspace</p>
        <SellerNav />

        <div className="mm-seller-session">
          <span className="mm-kicker">Signed in</span>
          <UserButton />
          <form action={signOutAction}>
            <button type="submit" className="mm-seller-signout">
              <LogOut size={13} aria-hidden="true" />
              Sign out
            </button>
          </form>
        </div>

        <p className="mm-seller-sidebar-note">
          Evidence and agreement records are read from the Verifund control
          plane for this seller only.
        </p>
      </aside>

      <div className="mm-seller-frame">
        <header className="mm-seller-topbar">
          <div>
            <span className="mm-kicker">Fulfillment workspace</span>
            <strong>{orgId ?? "Seller"}</strong>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Link
              href="/"
              className="mm-text-action"
              style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
            >
              <ArrowLeft size={13} aria-hidden="true" />
              Back to home
            </Link>
            <OrganizationSwitcher
              afterCreateOrganizationUrl="/seller/dashboard"
              afterSelectOrganizationUrl="/seller/dashboard"
              hidePersonal={false}
            />
            <span className="mm-status is-signal">Authenticated session</span>
          </div>
        </header>
        <main className="mm-seller-main">{children}</main>
      </div>
    </div>
  );
}
