"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AdminLink() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const adminQuery = useQuery({
    queryKey: ["admin-access"],
    queryFn: () =>
      fetch("/api/me/admin-access", { cache: "no-store" }).then(async (r) => {
        if (!r.ok) throw new Error(`admin-access ${r.status}`);
        return (await r.json()) as { admin: boolean };
      }),
    enabled: isSignedIn === true,
    staleTime: 30_000,
    retry: false,
  });

  if (adminQuery.data?.admin !== true) return null;

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => router.push("/admin")}
      leftIcon={<ShieldCheck size={14} aria-hidden="true" />}
    >
      Admin
    </Button>
  );
}
