"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export function MarketplaceLink() {
  const router = useRouter();
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => router.push("/")}
    >
      Marketplace
    </Button>
  );
}
