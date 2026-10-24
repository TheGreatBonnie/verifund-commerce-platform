import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("mm-skeleton", className)} aria-hidden="true" />;
}
