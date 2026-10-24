import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="mm-page-loading" aria-busy="true">
      <Skeleton className="mm-skeleton-block" />
    </div>
  );
}
