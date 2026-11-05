import { Status } from "@/components/ui/status";
import {
  payoutStatusLabel,
  payoutStatusTone,
  requirementStatusLabel,
  requirementStatusTone,
  transactionStateLabel,
  transactionStateTone,
} from "@/lib/seller-status";

export function TransactionStatusBadge({
  state,
}: {
  state?: string | null;
}) {
  return (
    <Status tone={transactionStateTone(state)}>
      {transactionStateLabel(state)}
    </Status>
  );
}

export function RequirementStatusBadge({
  status,
}: {
  status?: string | null;
}) {
  return (
    <Status tone={requirementStatusTone(status)}>
      {requirementStatusLabel(status)}
    </Status>
  );
}

export function PayoutStatusBadge({ status }: { status?: string | null }) {
  return (
    <Status tone={payoutStatusTone(status)}>
      {payoutStatusLabel(status)}
    </Status>
  );
}
