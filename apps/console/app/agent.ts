import { HttpAgent } from "@ag-ui/client";

export function createDefaultAgent(): HttpAgent {
  return new HttpAgent({
    url: process.env.BUYER_AGUI_URL ?? "http://127.0.0.1:9100/agui",
  });
}
