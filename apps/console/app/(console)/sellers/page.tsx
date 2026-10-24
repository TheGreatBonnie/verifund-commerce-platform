"use client";

import { Panel } from "@/components/ui/panel";
import { RegistryPanel } from "@/features/deal-room/components/registry-panel";
import { useRegistry } from "@/features/sellers/use-registry";

export default function SellersPage() {
  const { sellers, isLoading, error, refresh } = useRegistry();
  return (
    <Panel title="Sellers" kicker="Registry">
      <RegistryPanel sellers={sellers} loading={isLoading} error={error} onRefresh={refresh} />
    </Panel>
  );
}
