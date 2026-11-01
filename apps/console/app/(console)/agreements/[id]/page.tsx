import { notFound } from "next/navigation";
import { AgreementDocument } from "@/features/agreements/AgreementDocument";
import { AgreementSummary } from "@/features/agreements/AgreementSummary";
import { VersionHistory } from "@/features/agreements/VersionHistory";
import { AgreementDecisionPanel } from "./AgreementDecisionPanel";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

function actorHeaders() {
  return {
    "X-Actor-Id": "demo-buyer",
    "X-Actor-Type": "buyer",
  };
}

async function fetchAgreementServer(id: string): Promise<any | null> {
  try {
    const response = await fetch(
      `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}`,
      {
        cache: "no-store",
        headers: actorHeaders(),
      },
    );
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function fetchAgreementVersionsServer(id: string): Promise<any[]> {
  try {
    const response = await fetch(
      `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/versions`,
      {
        cache: "no-store",
        headers: actorHeaders(),
      },
    );
    if (!response.ok) return [];
    const body = await response.json();
    return Array.isArray(body) ? body : (body?.versions ?? []);
  } catch {
    return [];
  }
}

export default async function AgreementReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const agreement = await fetchAgreementServer(id);
  if (!agreement) notFound();

  const versions = await fetchAgreementVersionsServer(id);

  const handle =
    typeof query.task_id === "string" &&
    typeof query.context_id === "string" &&
    typeof query.run_id === "string"
      ? {
          task_id: query.task_id,
          context_id: query.context_id,
          run_id: query.run_id,
        }
      : null;

  return (
    <main className="mm-agreement-page">
      <h1>Agreement review</h1>
      <AgreementSummary agreement={agreement} />
      <AgreementDocument agreement={agreement} />
      <VersionHistory agreement={agreement} versions={versions} />
      <AgreementDecisionPanel agreement={agreement} handle={handle} />
    </main>
  );
}
