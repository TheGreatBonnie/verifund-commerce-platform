"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Kicker } from "@/components/ui/kicker";

type AgentCardPreviewProps = {
  card?: Record<string, unknown> | null;
  cardUrl?: string | null;
  cardHash?: string | null;
};

export function AgentCardPreview({ card, cardUrl, cardHash }: AgentCardPreviewProps) {
  const [showJson, setShowJson] = useState(false);

  if (!card) {
    return (
      <div className="mm-mono-note" style={{ margin: 0 }}>
        The public card appears here once the agent exists and a card preview is available.
      </div>
    );
  }

  const skills = Array.isArray(card.skills) ? (card.skills as Array<Record<string, unknown>>) : [];
  const interfaces = Array.isArray(card.supportedInterfaces)
    ? (card.supportedInterfaces as Array<Record<string, unknown>>)
    : [];
  const endpoint = interfaces[0]?.url ? String(interfaces[0].url) : cardUrl ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{String(card.name ?? "Seller agent")}</div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>
            {String(card.description ?? "")}
          </div>
        </div>
        <Badge>{String(card.version ?? "1.0.0")}</Badge>
      </div>

      {endpoint ? (
        <div className="mm-seller-field" style={{ margin: 0 }}>
          <span>Endpoint</span>
          <code style={{ fontSize: 11, wordBreak: "break-all", color: "var(--ink-soft)" }}>
            {endpoint}
          </code>
        </div>
      ) : null}

      <div className="mm-seller-field" style={{ margin: 0 }}>
        <span>Advertised skills</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {skills.length === 0 ? (
            <span style={{ color: "var(--muted)", fontSize: 11 }}>
              None advertised — every advertised skill derives from the tool allowlist.
            </span>
          ) : (
            skills.map((skill) => (
              <code
                key={String(skill.id)}
                title={String(skill.description ?? "")}
                className="mm-seller-format-chip"
              >
                {String(skill.id)}
              </code>
            ))
          )}
        </div>
      </div>

      {cardHash ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Kicker>Card hash</Kicker>
          <code style={{ fontSize: 10, color: "var(--muted)" }}>{String(cardHash).slice(0, 16)}…</code>
        </div>
      ) : null}

      <button
        type="button"
        className="mm-button mm-button-ghost mm-button-sm"
        style={{ alignSelf: "flex-start" }}
        onClick={() => setShowJson((v) => !v)}
        aria-expanded={showJson}
      >
        {showJson ? "Hide raw JSON" : "Show raw JSON"}
      </button>
      {showJson ? (
        <pre
          style={{
            margin: 0,
            padding: 10,
            overflowX: "auto",
            fontSize: 10,
            border: "1px solid var(--rule-strong)",
            background: "var(--paper)",
            maxHeight: 320,
          }}
        >
          {JSON.stringify(card, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
