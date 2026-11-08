import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

// The embedded PayPal checkout loads its v6 core SDK from
// www.(sandbox.)paypal.com, fraudnet from c.paypal.com, calls api-m, and opens
// checkout iframes. Keep these origins in sync with the PayPal card in
// features/chat/verifund-tools.tsx.
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.clerk.accounts.dev https://challenges.cloudflare.com https://*.protect.clerk.com https://www.paypal.com https://www.sandbox.paypal.com https://c.paypal.com",
  "style-src 'self' 'unsafe-inline'",
  // Seller catalogs import arbitrary image_url values, so images may come from
  // any HTTPS host (e.g. images.unsplash.com). Images cannot execute script.
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:* wss://realtime.intelligence.copilotkit.ai https://*.clerk.accounts.dev https://*.protect.clerk.com:* https://www.paypal.com https://www.sandbox.paypal.com https://api-m.paypal.com https://api-m.sandbox.paypal.com https://c.paypal.com",
  "frame-src https://challenges.cloudflare.com https://*.protect.clerk.com https://www.paypal.com https://www.sandbox.paypal.com",
  "worker-src 'self' blob:",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

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
            value: `${contentSecurityPolicy};`,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
