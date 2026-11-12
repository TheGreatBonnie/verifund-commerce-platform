"use client";

import type { AgreementView, AgreementVersionView } from "@/lib/types";

type Props = {
  agreement?: AgreementView | any;
  versions?: AgreementVersionView[] | any[];
  decisions?: any[];
};

export function VersionHistory({ agreement, versions, decisions }: Props) {
  const a = agreement ?? {};
  const vs =
    versions ??
    (Array.isArray(a.versions) ? a.versions : a.version ? [a.version] : []);
  const ds = decisions ?? (Array.isArray(a.decisions) ? a.decisions : []);

  return (
    <section data-testid="version-history" className="mm-version-history">
      <h4>Versions</h4>
      <ul>
        {vs.map((v: any, i: number) => (
          <li key={v?.version ?? i} data-testid="version-item">
            v{v?.version ?? i + 1} · {v?.agreement_hash ?? v?.hash ?? ""}
          </li>
        ))}
      </ul>
      <h4>Decisions</h4>
      <ul>
        {ds.map((d: any, i: number) => (
          <li key={d?.decision_id ?? i} data-testid="decision-item">
            {d?.party ?? ""} · {d?.decision ?? d?.status ?? ""} · v{d?.version ?? ""}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default VersionHistory;
