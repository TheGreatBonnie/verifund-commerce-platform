"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { setRole } from "./actions";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";

export function ChooseRoleClient() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const choose = (role: "buyer" | "seller") => {
    startTransition(async () => {
      await setRole(role);
      router.push("/post-auth");
    });
  };

  return (
    <main className="mm-auth-page">
      <Panel className="mm-dashboard-hero">
        <div className="mm-dashboard-hero-copy">
          <p className="mm-kicker">Welcome</p>
          <h1 className="mm-home-title">Choose your account type</h1>
          <p className="mm-deal-lede">
            Pick how you'll use MarketMesh. You can change this later.
          </p>
          <div className="mm-home-actions">
            <Button onClick={() => choose("buyer")} disabled={pending}>
              I'm a buyer
            </Button>
            <Button variant="outline" onClick={() => choose("seller")} disabled={pending}>
              I'm a seller
            </Button>
          </div>
        </div>
      </Panel>
    </main>
  );
}
