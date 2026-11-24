import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  css: { postcss: {} },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // CopilotKit's package entry imports a stylesheet; inline it so Vite,
    // rather than Node's ESM loader, resolves that import in tests. Vitest 3+
    // replaces this with deps.optimizer.{web,ssr}.include.
    server: { deps: { inline: ["@copilotkit/react-core"] } },
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["lib/**", "features/**/hooks/**", "components/ui/**"],
      thresholds: { lines: 60, functions: 60 },
    },
  },
  resolve: {
    alias: { "@": path.resolve(root, ".") },
  },
});
