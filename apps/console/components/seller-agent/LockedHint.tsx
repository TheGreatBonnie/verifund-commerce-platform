import Link from "next/link";
import { Lock } from "lucide-react";

export function LockedHint({ step, label }: { step: string; label: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        border: "1px dashed var(--rule-strong)",
        padding: "14px 12px",
        color: "var(--muted)",
        fontSize: 12,
      }}
    >
      <Lock size={14} aria-hidden="true" />
      <span>
        Create your seller agent in{" "}
        <Link href={`/seller/onboarding/${step}`} style={{ color: "var(--ink)", fontWeight: 600 }}>
          {label}
        </Link>{" "}
        to unlock this panel.
      </span>
    </div>
  );
}
