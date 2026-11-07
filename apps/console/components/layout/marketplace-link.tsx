"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export function MarketplaceLink() {
  const router = useRouter();
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => router.push("/")}
      leftIcon={<ArrowLeft size={14} aria-hidden="true" />}
    >
      Marketplace
    </Button>
  );
}
