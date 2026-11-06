"use client";

import { useState, useTransition } from "react";
import { FileUp, ListChecks, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { importCatalogAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";
import type { CatalogImportErrorEntry } from "@/lib/agent-types";

type CatalogImportPanelProps = {
  agentId?: string | null;
};

type ImportSummary = {
  inserted: number;
  updated: number;
  replaced: number;
};

export function CatalogImportPanel(_: CatalogImportPanelProps) {
  const [document, setDocument] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, startTransition] = useTransition();
  const [exampleBusy, setExampleBusy] = useState(false);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [errors, setErrors] = useState<CatalogImportErrorEntry[] | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const charCount = document.length;
  const canImport = charCount >= 2 && !busy;

  const resetFeedback = () => {
    setSummary(null);
    setErrors(null);
    setFormError(null);
  };

  const submit = (replaceCatalog: boolean) => {
    resetFeedback();
    startTransition(async () => {
      const result = await importCatalogAction(document, replaceCatalog);
      if (result.ok) {
        setSummary(result.data);
      } else {
        setFormError(result.error);
        if ("errors" in result && Array.isArray(result.errors)) {
          setErrors(result.errors);
        }
      }
    });
  };

  const onImportClick = () => {
    if (!replace) {
      submit(false);
      return;
    }
    const confirmed = window.confirm(
      "Replace the catalog? Products missing from the file will be deleted.",
    );
    if (confirmed) submit(true);
  };

  const loadExample = () => {
    setExampleBusy(true);
    resetFeedback();
    fetch("/example-catalog.json")
      .then((response) => {
        if (!response.ok) throw new Error("Could not load the example catalog.");
        return response.text();
      })
      .then((text) => setDocument(text))
      .catch((err: Error) => setFormError(err.message))
      .finally(() => setExampleBusy(false));
  };

  const onFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    resetFeedback();
    const reader = new FileReader();
    reader.onload = () => setDocument(String(reader.result ?? ""));
    reader.onerror = () => setFormError("Could not read that file.");
    reader.readAsText(file);
    event.target.value = "";
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
        Bring your products. Upload a JSON or YAML file, paste a document, or start from the
        example. Re-importing upserts by SKU; replacing is always explicit.
      </p>

      <div className="mm-seller-format-row">
        <label className="mm-button mm-button-outline mm-button-sm" style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 }}>
          <FileUp size={13} aria-hidden="true" />
          Upload .json / .yaml
          <input
            type="file"
            accept=".json,.yaml,.yml,application/json,application/octet-stream,text/yaml"
            onChange={onFile}
            style={{ display: "none" }}
          />
        </label>
        <button type="button" className="mm-button mm-button-outline mm-button-sm" onClick={loadExample} disabled={exampleBusy}>
          <Wand2 size={13} aria-hidden="true" />
          {exampleBusy ? "Loading example…" : "Load example catalog"}
        </button>
        <a className="mm-button mm-button-ghost mm-button-sm" href="/example-catalog.json" download>
          Download example (JSON)
        </a>
        <a className="mm-button mm-button-ghost mm-button-sm" href="/example-catalog-template.yaml" download>
          Download template (YAML)
        </a>
      </div>

      <label className="mm-seller-field" style={{ margin: 0 }}>
        <span style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Catalog document</span>
          <span aria-live="polite">{charCount.toLocaleString()} chars</span>
        </span>
        <textarea
          rows={8}
          value={document}
          onChange={(event) => {
            setDocument(event.target.value);
            resetFeedback();
          }}
          placeholder='{"version": 1, "products": [ … ]}  — or  version: 1\nproducts:\n  - sku: …'
          spellCheck={false}
          style={{ minHeight: 150, fontFamily: "var(--font-spline-sans-mono), monospace", fontSize: 10 }}
        />
      </label>

      <label
        htmlFor="replace-catalog"
        style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 11, color: "var(--ink-soft)", cursor: "pointer" }}
      >
        <input
          id="replace-catalog"
          type="checkbox"
          checked={replace}
          onChange={(event) => setReplace(event.target.checked)}
          style={{ marginTop: 2, accentColor: "var(--signal)" }}
        />
        <span>
          Replace the whole catalog (delete products missing from this file).
          You will be asked to confirm before anything is removed.
        </span>
      </label>

      {formError ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {formError}
        </p>
      ) : null}

      {errors?.length ? (
        <div style={{ overflowX: "auto", border: "1px solid var(--rule-strong)" }}>
          <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--rule-strong)" }}>Row</th>
                <th style={{ textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--rule-strong)" }}>Field</th>
                <th style={{ textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--rule-strong)" }}>Problem</th>
              </tr>
            </thead>
            <tbody>
              {errors.map((entry, index) => (
                <tr key={index}>
                  <td style={{ padding: "6px 8px", verticalAlign: "top" }}>{entry.row ?? "—"}</td>
                  <td style={{ padding: "6px 8px", verticalAlign: "top" }}><code>{entry.field ?? "—"}</code></td>
                  <td style={{ padding: "6px 8px", verticalAlign: "top" }}>{entry.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {summary ? (
        <p role="status" style={{ margin: 0, fontSize: 12, color: "var(--signal-deep)", display: "flex", alignItems: "center", gap: 8 }}>
          <ListChecks size={14} aria-hidden="true" />
          Imported — {summary.inserted} inserted, {summary.updated} updated
          {summary.replaced ? `, ${summary.replaced} removed` : ""}.
        </p>
      ) : null}

      <div>
        <Button onClick={onImportClick} disabled={!canImport} loading={busy}>
          {replace ? "Replace catalog (confirm)" : "Import catalog"}
        </Button>
      </div>
    </div>
  );
}
