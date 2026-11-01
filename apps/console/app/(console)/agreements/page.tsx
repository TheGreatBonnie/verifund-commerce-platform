import Link from "next/link";
import { AgreementSummary } from "@/features/agreements/AgreementSummary";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

function actorHeaders() {
  return {
    "X-Actor-Id": "demo-buyer",
    "X-Actor-Type": "buyer",
  };
}

async function fetchAgreementsServer(): Promise<any[]> {
  try {
    const response = await fetch(`${CONTROL_PLANE}/agreements`, {
      cache: "no-store",
      headers: actorHeaders(),
    });
    if (!response.ok) return [];
    const body = await response.json();
    return Array.isArray(body) ? body : [];
  } catch {
    return [];
  }
}

export default async function AgreementsPage() {
  const agreements = await fetchAgreementsServer();

  return (
    <main className="mm-agreements-page">
      <header className="mm-section-head">
        <div>
          <p className="mm-kicker">Agreements</p>
          <h1>Agreement reviews</h1>
        </div>
      </header>
      {agreements.length === 0 ? (
        <p>No agreements yet. They appear here once a Verifund run creates one.</p>
      ) : (
        <div className="mm-agreements-list">
          {agreements.map((agreement: any) => (
            <article key={agreement.agreement_id} className="mm-agreement-card">
              <AgreementSummary agreement={agreement} />
              <Link href={`/agreements/${agreement.agreement_id}`}>
                Review agreement
              </Link>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
