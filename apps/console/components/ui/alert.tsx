import { CircleAlert, X } from "lucide-react";
import { cn } from "@/lib/cn";

export interface AlertProps {
  message: string;
  onDismiss?: () => void;
  className?: string;
}

export function Alert({ message, onDismiss, className }: AlertProps) {
  return (
    <div className={cn("mm-alert", className)} role="alert">
      <CircleAlert size={16} aria-hidden="true" />
      <span>{message}</span>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} aria-label="Dismiss">
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
