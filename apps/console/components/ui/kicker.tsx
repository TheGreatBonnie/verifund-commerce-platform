import { cn } from "@/lib/cn";

export function Kicker({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("mm-kicker", className)}>{children}</span>;
}
