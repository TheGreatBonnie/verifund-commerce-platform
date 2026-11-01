import { notFound } from "next/navigation";
import { fetchAgreement, fetchAgreementVersions } from "@/lib/api";
import { AgreementDocument } from "@/features/agreements/AgreementDocument";
import { AgreementSummary } from "@/features/agreements/AgreementSummary";
import { VersionHistory } from "@/features/agreements/VersionHistory";
import { AgreementDecisionPanel } from "./AgreementDecisionPanel";

export default async function AgreementReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const query = await searchParams;
  let agreement: any;
  try {
    agreement = await fetchAgreement(id);
  } catch {
    notFound();
  }
  if (!agreement) notFound();

  let versions: any[] = [];
  try {
    versions = await fetchAgreementVersions(id);
  } catch {
    versions = [];
  }

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
