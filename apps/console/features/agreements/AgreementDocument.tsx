"use client";

import type { AgreementView } from "@/lib/types";

type Props = {
  agreement?: AgreementView | any;
  html?: string;
  digest?: string;
  version?: number;
};

export function AgreementDocument({ agreement, html, digest, version }: Props) {
  const a = agreement ?? {};
  const d = digest ?? a.agreement_hash ?? a.version?.agreement_hash ?? a.hash;
  const v = version ?? a.current_version ?? a.agreement_version ?? a.version?.version;
  const terms = a.terms ?? a.version?.terms ?? a;

  return (
    <section data-testid="agreement-document" className="mm-agreement-document">
      {v != null ? <p>Version {v}</p> : null}
      {d ? (
        <p data-testid="agreement-digest" className="mm-mono-note">
          {d}
        </p>
      ) : null}
      {html ? (
        <div
          data-testid="agreement-html"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre data-testid="agreement-terms">
          {typeof terms === "string" ? terms : JSON.stringify(terms, null, 2)}
        </pre>
      )}
    </section>
  );
}

export default AgreementDocument;
