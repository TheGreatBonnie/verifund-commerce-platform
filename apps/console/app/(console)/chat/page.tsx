"use client";

import { useRouter } from "next/navigation";
import { useFrontendTool, CopilotThreadsDrawer } from "@copilotkit/react-core/v2";
import { Chat } from "@/features/chat/chat";
import { config } from "@/lib/config";

const LAST_APP_PATH_KEY = "marketmesh:lastAppPath";

/** Chat-only surface: the buyer chat full-screen, no app chrome. */
export default function ChatPage() {
  const router = useRouter();

  const lastAppPath = () => {
    try {
      return window.sessionStorage.getItem(LAST_APP_PATH_KEY) ?? "/";
    } catch {
      return "/";
    }
  };

  useFrontendTool({
    agentId: "marketmesh_orchestrator",
    name: "enableAppMode",
    description: "Return to the full MarketMesh app (marketplace, runs, sellers).",
    handler: async () => {
      router.push(lastAppPath());
    },
  });

  useFrontendTool({
    agentId: "marketmesh_orchestrator",
    name: "enableChatMode",
    description: "Show only the chat full-screen.",
    handler: async () => {
      router.push("/chat");
    },
  });

  return (
    <div className="mm-chat-drawer-layout">
      <CopilotThreadsDrawer agentId="marketmesh_orchestrator" />
      <div className="mm-chat-full">
        <Chat
          variant="embedded"
          onRunSample={() => {}}
          isRunning={false}
          isReady
          verifundMode={config.verifundMode}
        />
      </div>
    </div>
  );
}
