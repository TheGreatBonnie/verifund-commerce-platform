import { FulfillmentDetail } from "@/components/buyer/fulfillment/fulfillment-detail";

export default async function FulfillmentDetailPage({
  params,
}: {
  params: Promise<{ transactionId: string }>;
}) {
  const { transactionId } = await params;
  return <FulfillmentDetail transactionId={transactionId} />;
}
