import { notFound } from "next/navigation";
import { fetchAgreement, fetchAgreementVersions } from "@/lib/api";
import { AgreementDocument } from "@/features/agreements/AgreementDocument";
import { AgreementSummary } from "@/features/agreements/AgreementSummary";
import { ApprovalActions } from "@/features/agreements/ApprovalActions";
import { VersionHistory } from "@/features/agreements/VersionHistory";

export default async function AgreementReviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
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

  return (
    <main className="mm-agreement-page">
      <h1>Agreement review</h1>
      <AgreementSummary agreement={agreement} />
      <AgreementDocument agreement={agreement} />
      <VersionHistory agreement={agreement} versions={versions} />
      <ApprovalActions agreement={agreement} />
    </main>
  );
}
