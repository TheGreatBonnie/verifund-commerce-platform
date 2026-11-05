import Link from "next/link";
import { LogOut, ShieldCheck } from "lucide-react";
import { SellerNav } from "@/components/seller/seller-nav";
import { formatDateTime } from "@/lib/format";
import { readSellerSession } from "@/lib/seller-api";
import { signOutAction } from "./actions";

export const dynamic = "force-dynamic";

function AccessGate() {
  return (
    <main className="mm-seller-gate">
      <div className="mm-seller-gate-card">
        <div className="mm-seller-gate-mark" aria-hidden="true">
          <ShieldCheck size={27} />
        </div>
        <p className="mm-kicker">Verifund seller center</p>
        <h1>Seller access required</h1>
        <p>
          Open the single-use invitation link issued for your transaction. The
          control plane exchanges it for a transaction-scoped seller session and
          stores it in an HttpOnly cookie, so the bearer token never reaches the
          browser.
        </p>
        <p className="mm-mono-note">
          Transactions, evidence, and payout records are scoped to the invited
          seller.
        </p>
        <Link className="mm-button" href="/">
          Return to MarketMesh
        </Link>
      </div>
    </main>
  );
}

export default async function SellerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await readSellerSession();
  if (!session) return <AccessGate />;

  return (
    <div className="mm-seller-shell">
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
          <strong>{session.sellerId ?? "Seller session"}</strong>
          <span>
            {session.expiresAt
              ? `Session expires ${formatDateTime(session.expiresAt.toISOString())}`
              : "Transaction-scoped access"}
          </span>
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
            <strong>{session.sellerId ?? "Seller"}</strong>
          </div>
          <span className="mm-status is-signal">Authenticated session</span>
        </header>
        <main className="mm-seller-main">{children}</main>
      </div>
    </div>
  );
}
