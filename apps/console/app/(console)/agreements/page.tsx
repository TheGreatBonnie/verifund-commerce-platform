import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { AgreementSummary } from "@/features/agreements/AgreementSummary";
import { controlPlaneForUser } from "@/lib/control-plane";

async function fetchAgreementsServer(): Promise<any[]> {
  try {
    const response = await controlPlaneForUser("/agreements");
    if (!response.ok) return [];
    const body = await response.json();
    return Array.isArray(body) ? body : [];
  } catch {
    return [];
  }
}

export default async function AgreementsPage() {
  await auth.protect();
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
              <Link
                href={`/agreements/${agreement.agreement_id}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Review agreement
              </Link>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
