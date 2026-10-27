"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { createQueryClient } from "@/lib/query-client";

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => createQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
