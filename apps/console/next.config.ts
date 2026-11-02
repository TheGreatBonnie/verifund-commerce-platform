import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

const nextConfig: NextConfig = {
  // Pin the root to this folder. Otherwise a lockfile in a parent folder
  // becomes the workspace root. This value also sets the file tracing root.
  turbopack: { root: fileURLToPath(new URL(".", import.meta.url)) },
  output: "standalone",
  env: {
    NEXT_PUBLIC_MARKETMESH_LLM_MODE:
      process.env.MARKETMESH_LLM_MODE ?? "scripted",
    NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED: process.env.CPK_INTELLIGENCE_API_KEY
      ? "true"
      : "false",
    NEXT_PUBLIC_VERIFUND_MODE: process.env.VERIFUND_MODE ?? "sandbox",
  },
  serverExternalPackages: ["@copilotkit/runtime"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          {
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:* wss://realtime.intelligence.copilotkit.ai; frame-ancestors 'none';",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
