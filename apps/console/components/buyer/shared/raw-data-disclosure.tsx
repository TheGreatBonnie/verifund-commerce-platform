import { cn } from "@/lib/cn";

export function RawDataDisclosure({
  label,
  value,
  className,
}: {
  label: string;
  value: unknown;
  className?: string;
}) {
  const stripped = label.replace(/^View\s+/i, "");
  const ariaLabel = stripped.charAt(0).toUpperCase() + stripped.slice(1);
  return (
    <details className={cn("mm-buyer-raw", className)}>
      <summary>{label}</summary>
      <pre tabIndex={0} aria-label={ariaLabel}>
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}
