import { type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Kicker } from "./kicker";

export interface PanelProps {
  title?: string;
  kicker?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, kicker, actions, children, className }: PanelProps) {
  return (
    <section className={cn("mm-panel", className)}>
      {kicker || title || actions ? (
        <header className="mm-panel-head">
          <div>
            {kicker ? <Kicker>{kicker}</Kicker> : null}
            {title ? <h2>{title}</h2> : null}
          </div>
          {actions}
        </header>
      ) : null}
      {children}
    </section>
  );
}
