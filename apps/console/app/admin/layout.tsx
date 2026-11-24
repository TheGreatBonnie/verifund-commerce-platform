import { redirect } from "next/navigation";
import Link from "next/link";
import { LogOut, ShieldCheck } from "lucide-react";
import { UserButton } from "@clerk/nextjs";
import { AdminNav } from "@/components/admin/admin-nav";
import { MarketplaceLink } from "@/components/layout/marketplace-link";
import { adminAccess } from "@/lib/admin-access";
import { signOutAction } from "./actions";

export const dynamic = "force-dynamic";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!(await adminAccess())) redirect("/");

  return (
    <div className="mm-seller-shell" suppressHydrationWarning>
      <aside className="mm-seller-sidebar">
        <Link href="/admin" className="mm-seller-brand">
          <span className="mm-seller-brand-mark" aria-hidden="true">
            <ShieldCheck size={19} />
          </span>
          <span>
            <strong>verifund</strong>
            <small>Platform admin</small>
          </span>
        </Link>

        <p className="mm-seller-nav-label">Workspace</p>
        <AdminNav />

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
          Platform transactions are read from the Verifund control plane for the
          configured PayPal platform account only.
        </p>
      </aside>

      <div className="mm-seller-frame">
        <header className="mm-seller-topbar">
          <div>
            <span className="mm-kicker">Platform operations</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <MarketplaceLink />
          </div>
        </header>
        <main className="mm-seller-main">{children}</main>
      </div>
    </div>
  );
}
