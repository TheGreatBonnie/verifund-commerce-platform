import { ArrowLeft, LockKeyhole, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { AccessExchangeForm } from "./access-exchange-form";

export const dynamic = "force-dynamic";

export default async function FulfillmentAccessPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;

  return (
    <main className="mm-seller-gate">
      <Link href="/" className="mm-seller-access-back">
        <ArrowLeft size={13} aria-hidden="true" />
        Back to MarketMesh
      </Link>
      <div className="mm-seller-gate-card">
        <div className="mm-seller-gate-mark" aria-hidden="true">
          <ShieldCheck size={27} />
        </div>
        <p className="mm-kicker">Verifund seller center</p>
        <h1>Secure fulfillment access</h1>
        <p>
          You are opening a transaction-scoped Verifund workspace. Confirm to
          exchange this single-use invitation for a seller session.
        </p>
        <div className="mm-seller-access-summary">
          <span>
            <LockKeyhole size={13} aria-hidden="true" />
            Single-use invitation
          </span>
          <span>Operations-issued</span>
        </div>
        <AccessExchangeForm token={token} />
      </div>
    </main>
  );
}
