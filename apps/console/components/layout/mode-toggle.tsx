"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/cn";

const LAST_APP_PATH_KEY = "marketmesh:lastAppPath";

/**
 * Chat | App mode switch. Chat mode is the dedicated /chat route (chat
 * full-screen, no app chrome); App mode returns to the last app page.
 */
export function ModeToggle() {
  const pathname = usePathname();
  const router = useRouter();
  const chatOnly = pathname === "/chat";
  const [lastAppPath, setLastAppPath] = useState("/");

  useEffect(() => {
    let stored = "/";
    try {
      stored = window.sessionStorage.getItem(LAST_APP_PATH_KEY) ?? "/";
    } catch {
      stored = "/";
    }
    setLastAppPath(stored);
    if (!chatOnly) {
      try {
        window.sessionStorage.setItem(LAST_APP_PATH_KEY, pathname ?? "/");
      } catch {
        // Mode switching still works without persistence.
      }
      setLastAppPath(pathname ?? "/");
    }
  }, [pathname, chatOnly]);

  return (
    <div className="mm-mode-toggle" role="group" aria-label="View mode">
      <button
        type="button"
        className={cn("mm-mode-toggle-button", chatOnly && "is-active")}
        aria-pressed={chatOnly}
        aria-label="Chat only"
        onClick={() => router.push("/chat")}
      >
        Chat
      </button>
      <button
        type="button"
        className={cn("mm-mode-toggle-button", !chatOnly && "is-active")}
        aria-pressed={!chatOnly}
        aria-label="Full app"
        onClick={() => router.push(lastAppPath)}
      >
        App
      </button>
    </div>
  );
}
