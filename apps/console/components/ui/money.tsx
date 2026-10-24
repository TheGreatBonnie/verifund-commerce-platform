import { money as formatMoney } from "@/lib/format";
import { cn } from "@/lib/cn";

export interface MoneyProps {
  cents: number;
  className?: string;
  subCentsClassName?: string;
}

export function Money({ cents, className, subCentsClassName }: MoneyProps) {
  const formatted = formatMoney(cents);
  const whole = formatted.slice(0, -3);
  const centsPart = formatted.slice(-3);
  return (
    <span className={cn("mm-money", className)}>
      {whole}
      <span className={cn("mm-money-cents", subCentsClassName)}>{centsPart}</span>
    </span>
  );
}
