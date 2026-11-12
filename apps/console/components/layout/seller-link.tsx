"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SellerLink() {
  const router = useRouter();
  const { isSignedIn, orgId } = useAuth();

  const sellerAccessQuery = useQuery({
    queryKey: ["seller-access", orgId ?? "no-org"],
    queryFn: () =>
      fetch("/api/me/seller-access", { cache: "no-store" }).then(async (r) => {
        if (!r.ok) throw new Error(`seller-access ${r.status}`);
        return (await r.json()) as { access: string; orgId: string | null };
      }),
    enabled: isSignedIn === true && !!orgId,
    staleTime: 30_000,
    retry: false,
  });

  const sellerAccess = sellerAccessQuery.data?.access;
  const isSeller = sellerAccess === "workspace" || sellerAccess === "read_only";
  const isOnboarding = sellerAccess === "onboarding";

  if (!isSeller && !isOnboarding) return null;

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => router.push(isSeller ? "/seller/dashboard" : "/seller/onboarding")}
      leftIcon={<ShieldCheck size={14} aria-hidden="true" />}
    >
      {isSeller ? "Seller dashboard" : "Continue seller onboarding"}
    </Button>
  );
}
