"use client";

import {
  CopilotChat,
  CopilotChatConfigurationProvider,
  CopilotKitProvider,
} from "@copilotkit/react-core/v2";

export default function Home() {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
      <CopilotChatConfigurationProvider agentId="marketmesh_buyer">
        <main className="min-h-dvh bg-[#F4F0E6] p-8 text-[#171713]">
          <h1 className="font-serif text-4xl">MarketMesh</h1>
          <p className="mt-2 text-sm text-[#5E5A50]">
            A2A commerce exchange — console wiring in progress.
          </p>
          <div className="mt-8 h-[70dvh] max-w-xl">
            <CopilotChat />
          </div>
        </main>
      </CopilotChatConfigurationProvider>
    </CopilotKitProvider>
  );
}
