import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" aria-label={label} className={cn("mm-spinner", className)}>
      <Loader2 size={16} className="is-spinning" aria-hidden="true" />
    </span>
  );
}
